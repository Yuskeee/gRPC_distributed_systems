import grpc
from concurrent import futures
import sched
import time
import threading
import sys
import os

from google.protobuf.timestamp_pb2 import Timestamp

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../grpcFiles')))

import auction_pb2
import auction_pb2_grpc
import bid_pb2
import bid_pb2_grpc

def datetime_to_timestamp(dt):
    ts = Timestamp()
    ts.FromDatetime(dt)
    return ts

def timestamp_to_datetime(ts):
    return ts.ToDatetime()

def now_timestamp():
    return datetime_to_timestamp(dt_module.datetime.now())

def iso_to_timestamp(iso_string):
    dt = dt_module.datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
    return datetime_to_timestamp(dt)

class AuctionService(auction_pb2_grpc.AuctionServiceServicer):
    def __init__(self, bid_address="localhost:50052", gateway_address="localhost:50050"):
        self.auctions = []
        self.current_id = 0
        self.lock = threading.Lock()

        self.bid_address = bid_address
        self.bid_channel = grpc.insecure_channel(
            self.bid_address,
            options=[
                ('grpc.keepalive_time_ms', 10000),
                ('grpc.keepalive_timeout_ms', 5000),
            ]
        )
        self.bid_stub = bid_pb2_grpc.BidServiceStub(self.bid_channel)
        
        # Conexão com Gateway (para callbacks)
        self.gateway_address = gateway_address
        self.gateway_channel = None
        self.gateway_stub = None
        self._setup_gateway_connection()

        # Scheduler
        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.running = True

        self.sched_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.sched_thread.start()
        
        print(f"[AuctionService] Initialized")
        print(f"  BidService: {self.bid_address}")
        print(f"  Gateway: {self.gateway_address}")
    
    def _setup_gateway_connection(self):
        try:
            self.gateway_channel = grpc.insecure_channel(
                self.gateway_address,
                options=[
                    ('grpc.keepalive_time_ms', 10000),
                    ('grpc.keepalive_timeout_ms', 5000),
                ]
            )
            self.gateway_stub = auction_pb2_grpc.AuctionCallbackServiceStub(self.gateway_channel)
            print(f"[AuctionService] ✓ Connected to Gateway at {self.gateway_address}")
        except Exception as e:
            print(f"[AuctionService] ✗ Failed to connect to Gateway: {e}")

    def _generate_id(self):
        self.current_id += 1
        return self.current_id

    def CreateAuction(self, request, context):
        with self.lock:
            auction_id = self._generate_id()
            
            auction = auction_pb2.Auction(
                id=auction_id,
                description=request.description,
                start_time=request.start_time,
                end_time=request.end_time,
                status="pending"
            )
            self.auctions.append(auction)
            
            print(f"[AuctionService] Auction {auction_id} created")
            
            return auction

    def ListAuctions(self, request, context):
        with self.lock:
            response = auction_pb2.ListAuctionsResponse()
            
            # Filtra por status se especificado
            if request.filter and request.filter != "all":
                filtered = [a for a in self.auctions if a.status == request.filter]
                response.auctions.extend(filtered)
            else:
                response.auctions.extend(self.auctions)
            
            print(f"[AuctionService] Listed {len(response.auctions)} auctions (filter: {request.filter or 'all'})")
            return response
    
    def GetAuction(self, request, context):
        with self.lock:
            for auction in self.auctions:
                if auction.id == request.auction_id:
                    print(f"[AuctionService] Auction {request.auction_id} found")
                    return auction_pb2.GetAuctionResponse(
                        found=True,
                        auction=auction
                    )
            
            print(f"[AuctionService] Auction {request.auction_id} not found")
            return auction_pb2.GetAuctionResponse(found=False)

    def _run_scheduler(self):
        self._schedule_check()
        self.scheduler.run()

    def _schedule_check(self):
        if self.running:
            self._check_auctions()
            self.scheduler.enter(1, 1, self._schedule_check)

    def _check_auctions(self):
        now = time.time()
        
        with self.lock:
            for auction in self.auctions:
                # Converte Timestamps para Unix timestamps
                start_unix = timestamp_to_datetime(auction.start_time).timestamp()
                end_unix = timestamp_to_datetime(auction.end_time).timestamp()
                
                # Leilão iniciando
                if auction.status == "pending" and now >= start_unix:
                    auction.status = "active"
                    print(f"[AuctionService] Auction {auction.id} STARTED")

                    # Notifica BidService
                    try:
                        self.bid_stub.AuctionStarted(
                            bid_pb2.AuctionEventRequest(auction_id=auction.id),
                            timeout=5.0
                        )
                        print(f"  ✓ BidService notified")
                    except Exception as e:
                        print(f"  ✗ Failed to notify BidService: {e}")
                    
                    # Notifica Gateway via callback gRPC
                    self._notify_gateway_auction_started(auction.id, auction.start_time)

                # Leilão encerrando
                elif auction.status == "active" and now >= end_unix:
                    auction.status = "closed"
                    print(f"[AuctionService] Auction {auction.id} CLOSED")

                    # Notifica BidService e obtém vencedor
                    try:
                        resp = self.bid_stub.AuctionClosed(
                            bid_pb2.AuctionEventRequest(auction_id=auction.id),
                            timeout=5.0
                        )
                        
                        if resp.has_winner:
                            print(f"  Winner: {resp.winner_id[:12]}...")
                            print(f"  Value: ${resp.value:.2f}")
                            
                            # Notifica Gateway sobre vencedor
                            self._notify_gateway_auction_closed(
                                auction_id=auction.id,
                                has_winner=True,
                                winner_id=resp.winner_id,
                                winning_value=resp.value,
                                end_time_ts=auction.end_time
                            )
                        else:
                            print(f"  No winner")
                            self._notify_gateway_auction_closed(
                                auction_id=auction.id,
                                has_winner=True,
                                winner_id=resp.winner_id,
                                winning_value=resp.value,
                                end_time_ts=auction.end_time  # ✅ CORRETO
                            )
                            
                    except Exception as e:
                        print(f"  ✗ Failed to notify BidService: {e}")
    
    def _notify_gateway_auction_started(self, auction_id, start_time_ts):
        if not self.gateway_stub:
            self._setup_gateway_connection()
            if not self.gateway_stub:
                return
        
        try:
            notification = auction_pb2.AuctionStartedNotification(
                auction_id=auction_id,
                start_time=start_time_ts
            )
            
            response = self.gateway_stub.OnAuctionStarted(notification, timeout=5.0)
            
            if response.success:
                print(f"  ✓ Gateway notified (auction started)")
            else:
                print(f"  ✗ Gateway callback failed: {response.message}")
                
        except grpc.RpcError as e:
            print(f"  ✗ Gateway callback error: {e.code()}: {e.details()}")
        except Exception as e:
            print(f"  ✗ Gateway callback error: {e}")
    
    def _notify_gateway_auction_closed(self, auction_id, has_winner, winner_id, 
                                       winning_value, end_time_ts):
        if not self.gateway_stub:
            self._setup_gateway_connection()
            if not self.gateway_stub:
                return
        
        try:
            notification = auction_pb2.AuctionClosedNotification(
                auction_id=auction_id,
                has_winner=has_winner,
                winner_id=winner_id,
                winning_value=winning_value,
                end_time=end_time_ts
            )
            
            response = self.gateway_stub.OnAuctionClosed(notification, timeout=5.0)
            
            if response.success:
                print(f"  ✓ Gateway notified (auction closed)")
            else:
                print(f"  ✗ Gateway callback failed: {response.message}")
                
        except grpc.RpcError as e:
            print(f"  ✗ Gateway callback error: {e.code()}: {e.details()}")
        except Exception as e:
            print(f"  ✗ Gateway callback error: {e}")

    def stop(self):
        self.running = False
        if self.bid_channel:
            self.bid_channel.close()
        if self.gateway_channel:
            self.gateway_channel.close()


def serve(port=50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    auction_service = AuctionService(
        bid_address="localhost:50052",
        gateway_address="localhost:50050"
    )
    auction_pb2_grpc.add_AuctionServiceServicer_to_server(
        auction_service, server
    )
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    
    print("=" * 60)
    print("AUCTION SERVICE (gRPC)")
    print("=" * 60)
    print(f"Server listening on port {port}")
    print("=" * 60)
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("\n[AuctionService] Shutting down...")
        auction_service.stop()
        server.stop(0)


if __name__ == '__main__':
    serve()
