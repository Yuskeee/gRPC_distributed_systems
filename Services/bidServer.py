import threading
from concurrent import futures

import grpc
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../grpcFiles')))

import bid_pb2
import bid_pb2_grpc
import payment_pb2
import payment_pb2_grpc
import auction_pb2

class BidService(bid_pb2_grpc.BidServiceServicer):

    def __init__(self, payment_service_address: str = "localhost:50053", gateway_address: str = "localhost:50050") -> None:
        self.highest_bids: dict[int, dict] = {}
        self.auction_status: dict[int, str] = {}
        self._lock = threading.Lock()
        
        self.payment_service_address = payment_service_address
        self.payment_channel = None
        self.payment_stub = None
        self._setup_payment_client()
        
        self.gateway_address = gateway_address
        self.gateway_channel = None
        self.gateway_stub = None
        self._setup_gateway_client()

    def _setup_payment_client(self):
        try:
            self.payment_channel = grpc.insecure_channel(
                self.payment_service_address,
                options=[('grpc.keepalive_time_ms', 10000), ('grpc.keepalive_timeout_ms', 5000)]
            )
            self.payment_stub = payment_pb2_grpc.PaymentServiceStub(self.payment_channel)
            print(f"[BidService] ✓ Connected to PaymentService at {self.payment_service_address}")
        except Exception as e:
            print(f"[BidService] ✗ Failed to connect to PaymentService: {e}")
    
    def _setup_gateway_client(self):
        try:
            self.gateway_channel = grpc.insecure_channel(
                self.gateway_address,
                options=[('grpc.keepalive_time_ms', 10000), ('grpc.keepalive_timeout_ms', 5000)]
            )
            self.gateway_stub = bid_pb2_grpc.BidCallbackServiceStub(self.gateway_channel)
            print(f"[BidService] ✓ Connected to Gateway at {self.gateway_address}")
        except Exception as e:
            print(f"[BidService] ✗ Failed to connect to Gateway: {e}")

    def AuctionStarted(self, request, context):
        try:
            auction_id = request.auction_id
            with self._lock:
                self.auction_status[auction_id] = "active"
                self.highest_bids[auction_id] = None
            print(f"[BidService] Auction {auction_id} started.")
            return auction_pb2.AuctionEventAck(success=True, message="Auction started")
        except Exception as e:
            print(f"[BidService] Error on auction_started: {e}")
            return auction_pb2.AuctionEventAck(success=False, message=str(e))

    def AuctionClosed(self, request, context):
        try:
            auction_id = request.auction_id
            with self._lock:
                self.auction_status[auction_id] = "closed"
                winner_info = self.highest_bids.get(auction_id)

            if winner_info:
                print(f"[BidService] Auction {auction_id} closed! Winner: {winner_info['user_id'][:8]}...")
                
                self._notify_payment_service(
                    auction_id=auction_id,
                    winner_id=winner_info["user_id"],
                    value=winner_info["amount"]
                )
                
                return bid_pb2.AuctionClosedResponse(
                    auction_id=auction_id,
                    has_winner=True,
                    winner_id=winner_info["user_id"],
                    value=winner_info["amount"],
                )
            else:
                print(f"[BidService] Auction {auction_id} closed. No valid bids.")
                return bid_pb2.AuctionClosedResponse(auction_id=auction_id, has_winner=False)
        except Exception as e:
            print(f"[BidService] Error on auction_closed: {e}")
            context.set_details(str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            return bid_pb2.AuctionClosedResponse(auction_id=request.auction_id, has_winner=False)

    def _notify_payment_service(self, auction_id: int, winner_id: str, value: float):
        if not self.payment_stub:
            self._setup_payment_client()
            if not self.payment_stub: return

        try:
            payment_request = payment_pb2.AuctionWinnerRequest(
                auction_id=auction_id, winner_id=winner_id, value=value, currency="BRL"
            )
            response = self.payment_stub.ProcessAuctionWinner(payment_request, timeout=10.0)
            
            if response.success:
                print(f"[BidService] Payment link created: {response.payment_link}")
                self._notify_gateway_payment_link(
                    auction_id=auction_id,
                    customer_id=winner_id,
                    payment_link=response.payment_link,
                    transaction_id=response.transaction_id,
                    status=response.status,
                    value=value
                )
            else:
                print(f"[BidService] Payment service error: {response.message}")
        except grpc.RpcError as e:
            print(f"[BidService] gRPC error calling PaymentService: {e.code()}: {e.details()}")
        except Exception as e:
            print(f"[BidService] Unexpected error calling PaymentService: {e}")
    
    def _notify_gateway_payment_link(self, auction_id: int, customer_id: str, 
                                     payment_link: str, transaction_id: str, 
                                     status: str, value: float):
        if not self.gateway_stub:
            self._setup_gateway_client()
            if not self.gateway_stub: return
        
        try:
            notification = bid_pb2.PaymentLinkNotification(
                auction_id=auction_id,
                customer_id=customer_id,
                payment_link=payment_link,
                transaction_id=transaction_id,
                status=status,
                value=value
            )
            
            response = self.gateway_stub.OnPaymentLinkGenerated(notification, timeout=60.0)
            
            if response.success:
                print(f"[BidService] ✓ Gateway notified about payment link")
            else:
                print(f"[BidService] ✗ Gateway callback failed: {response.message}")
                
        except grpc.RpcError as e:
            print(f"[BidService] ✗ gRPC error notifying gateway: {e.code()}: {e.details()}")
        except Exception as e:
            print(f"[BidService] ✗ Error notifying gateway: {e}")

    def PlaceBid(self, request, context):
        try:
            user_id = request.user_id
            auction_id = int(request.auction_id)
            amount = request.amount

            with self._lock:
                if self.auction_status.get(auction_id) != "active":
                    return bid_pb2.PlaceBidResponse(accepted=False, reason="Auction is not active", auction_id=auction_id)

                current = self.highest_bids.get(auction_id)
                if current and amount <= current["amount"]:
                    return bid_pb2.PlaceBidResponse(accepted=False, reason="Bid too low", auction_id=auction_id)

                self.highest_bids[auction_id] = {"user_id": user_id, "amount": amount}

            print(f"[BidService] New highest bid for auction {auction_id}: {amount:.2f}")
            return bid_pb2.PlaceBidResponse(accepted=True, auction_id=auction_id, user_id=user_id, amount=amount)
        except Exception as e:
            print(f"[BidService] Error processing bid: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            return bid_pb2.PlaceBidResponse(accepted=False, reason=str(e))

    def close(self):
        if self.payment_channel: self.payment_channel.close()
        if self.gateway_channel: self.gateway_channel.close()

def serve(port: int = 50052):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bid_service = BidService()
    bid_pb2_grpc.add_BidServiceServicer_to_server(bid_service, server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print("BID SERVICE (gRPC)")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()