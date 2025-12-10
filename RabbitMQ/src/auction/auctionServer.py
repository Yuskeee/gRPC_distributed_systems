import grpc
from concurrent import futures
import sched
import time
import threading
import os
import sys

import auction_pb2
import auction_pb2_grpc
from bid import bid_pb2, bid_pb2_grpc

class AuctionService(auction_pb2_grpc.AuctionServiceServicer):
    def __init__(self):
        self.auctions = []
        self.current_id = 0
        self.lock = threading.Lock()

        self.bid_channel = grpc.insecure_channel("localhost:50052")
        self.bid_stub = bid_pb2_grpc.BidServiceStub(self.bid_channel)

        # Scheduler
        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.running = True

        self.sched_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.sched_thread.start()

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
            return auction

    def ListAuctions(self, request, context):
        with self.lock:
            response = auction_pb2.ListAuctionsResponse()
            response.auctions.extend(self.auctions)
            return response

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
                if auction.status == "pending" and now >= auction.start_time.seconds:
                    auction.status = "active"
                    print(f"Auction {auction.id} started.")

                    # Notify BidService that an auction has started
                    try:
                        self.bid_stub.AuctionStarted(
                            bid_pb2.AuctionEventRequest(auction_id=auction.id)
                        )
                    except Exception as e:
                        print(f"[AuctionService] Failed to notify BidService about start: {e}")

                elif auction.status == "active" and now >= auction.end_time.seconds:
                    auction.status = "closed"
                    print(f"Auction {auction.id} finished.")

                    # Notify BidService that an auction has closed and log winner info
                    try:
                        resp = self.bid_stub.AuctionClosed(
                            bid_pb2.AuctionEventRequest(auction_id=auction.id)
                        )
                        if resp.has_winner:
                            print(
                                f"[AuctionService] Winner for auction {resp.auction_id}: "
                                f"{resp.winner_id[:8]}... with {resp.value:.2f}"
                            )
                        else:
                            print(
                                f"[AuctionService] Auction {resp.auction_id} closed with no winner."
                            )
                    except Exception as e:
                        print(f"[AuctionService] Failed to notify BidService about close: {e}")

    def stop(self):
        self.running = False


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    auction_service = AuctionService()
    auction_pb2_grpc.add_AuctionServiceServicer_to_server(
        auction_service, server
    )
    server.add_insecure_port('[::]:50051')
    server.start()
    print("gRPC server started on port 50051")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        auction_service.stop()
        server.stop(0)


if __name__ == '__main__':
    serve()
