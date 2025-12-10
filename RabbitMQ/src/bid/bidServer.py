import threading
from concurrent import futures

import grpc

import bid_pb2
import bid_pb2_grpc


class BidService(bid_pb2_grpc.BidServiceServicer):

    def __init__(self) -> None:
        # auction_id -> {"user_id": str, "amount": float}
        self.highest_bids: dict[int, dict] = {}
        # auction_id -> "pending" | "active" | "closed"
        self.auction_status: dict[int, str] = {}
        self._lock = threading.Lock()


    def AuctionStarted(self, request, context):
        try:
            auction_id = request.auction_id
            with self._lock:
                self.auction_status[auction_id] = "active"
                self.highest_bids[auction_id] = None
            print(f"[BidService] Auction {auction_id} started.")
            return bid_pb2.AuctionEventAck(success=True, message="Auction started")
        except Exception as e:  # pragma: no cover - defensive logging
            print(f"[BidService] Error on auction_started: {e}")
            return bid_pb2.AuctionEventAck(success=False, message=str(e))

    def AuctionClosed(self, request, context):
        try:
            auction_id = request.auction_id
            with self._lock:
                self.auction_status[auction_id] = "closed"
                winner_info = self.highest_bids.get(auction_id)

            if winner_info:
                print(
                    f"[BidService] Auction {auction_id} closed! "
                    f"Winner: {winner_info['user_id'][:8]}..., "
                    f"Value: {winner_info['amount']:.2f}"
                )
                return bid_pb2.AuctionClosedResponse(
                    auction_id=auction_id,
                    has_winner=True,
                    winner_id=winner_info["user_id"],
                    value=winner_info["amount"],
                )
            else:
                print(f"[BidService] Auction {auction_id} closed. No valid bids.")
                return bid_pb2.AuctionClosedResponse(
                    auction_id=auction_id,
                    has_winner=False,
                )
        except Exception as e:  # pragma: no cover - defensive logging
            print(f"[BidService] Error on auction_closed: {e}")
            context.set_details(str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            return bid_pb2.AuctionClosedResponse(
                auction_id=request.auction_id,
                has_winner=False,
            )

    def PlaceBid(self, request, context):
        try:
            user_id = request.user_id
            auction_id = int(request.auction_id)
            amount = request.amount

            print(
                f"[BidService] Bid received: user {user_id[:8]}..., "
                f"auction {auction_id}, value {amount:.2f}"
            )

            with self._lock:
                # 1. Auction must exist and be active
                if self.auction_status.get(auction_id) != "active":
                    print("[BidService] Auction is not active. Ignoring bid.")
                    return bid_pb2.PlaceBidResponse(
                        accepted=False,
                        reason="Auction is not active",
                        auction_id=auction_id,
                        user_id=user_id,
                        amount=amount,
                    )

                # 2. Bid must be higher than current max
                current = self.highest_bids.get(auction_id)
                if current and amount <= current["amount"]:
                    print(
                        "[BidService] Bid not higher than current maximum. "
                        "Ignoring bid."
                    )
                    print(
                        f"[BidService] Ignored bid for auction {auction_id}: "
                        f"{amount:.2f} by user {user_id[:8]}..."
                    )
                    return bid_pb2.PlaceBidResponse(
                        accepted=False,
                        reason="Bid not higher than current maximum",
                        auction_id=auction_id,
                        user_id=user_id,
                        amount=amount,
                    )

                # Accept bid
                self.highest_bids[auction_id] = {"user_id": user_id, "amount": amount}

            print(
                f"[BidService] New highest bid for auction {auction_id}: "
                f"{amount:.2f} by user {user_id[:8]}..."
            )

            return bid_pb2.PlaceBidResponse(
                accepted=True,
                reason="",
                auction_id=auction_id,
                user_id=user_id,
                amount=amount,
            )
        except Exception as e:
            print(f"[BidService] Error processing bid: {e}")
            context.set_details(str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            return bid_pb2.PlaceBidResponse(
                accepted=False,
                reason=str(e),
                auction_id=request.auction_id,
                user_id=request.user_id,
                amount=request.amount,
            )


def serve(port: int = 50052) -> None:
    """Start the BidService gRPC server (similar style to auctionServer.py)."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bid_service = BidService()
    bid_pb2_grpc.add_BidServiceServicer_to_server(bid_service, server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"BidService gRPC server started on port {port}")

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == "__main__":
    serve()
