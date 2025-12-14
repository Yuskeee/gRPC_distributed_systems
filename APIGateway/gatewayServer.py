from flask import Flask, request, jsonify
from flask_sse import sse
from flask_cors import CORS
import time
import datetime as dt_module
import logging
import os
import threading
import queue
import gevent
from gevent import monkey
from gevent.pywsgi import WSGIServer
from concurrent import futures

monkey.patch_all(thread=False)

import grpc
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../grpcFiles')))

from google.protobuf.timestamp_pb2 import Timestamp

import auction_pb2, auction_pb2_grpc
import bid_pb2, bid_pb2_grpc

app = Flask(__name__)
CORS(app)
app.config["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://localhost:6379")
app.register_blueprint(sse, url_prefix='/events')

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

interests = {}  # {auction_id: set(user_id)}
interest_lock = threading.Lock()

sse_queue = queue.Queue()

def sse_worker():
    logger.info("[Gateway] SSE Worker started")
    while True:
        try:
            while sse_queue.empty():
                gevent.sleep(0.1)
            
            message_data = sse_queue.get()
            
            channel = message_data['channel']
            message = message_data['message']
            msg_type = message_data['type']
            
            with app.app_context():
                sse.publish(message, type=msg_type, channel=channel)
                
        except Exception as e:
            logger.error(f"[Gateway] Error in SSE worker: {e}")
            gevent.sleep(1)

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

class NotificationManager:
    def __init__(self):
        self.keep_alive_interval = 30
        self._start_keepalive()
    
    def _start_keepalive(self):
        def _send_keepalive():
            while True:
                time.sleep(self.keep_alive_interval)
                
                keep_alive_message = {
                    "event_type": "keepalive",
                    "payload": {"status": "alive"},
                    "timestamp": dt_module.datetime.now().isoformat()
                }
                with app.app_context():
                     sse.publish(keep_alive_message, type='keepalive')
        
        thread = threading.Thread(target=_send_keepalive, daemon=True)
        thread.start()
        logger.info("[Notification] Keep-alive thread started")
    
    def _queue_message(self, channel, msg_type, message):
        sse_queue.put({
            'channel': channel,
            'type': msg_type,
            'message': message
        })

    def notify_new_bid(self, payload):
        try:
            auction_id = str(payload.get('auction_id'))
            with interest_lock:
                if auction_id not in interests:
                    return
                interested_users = list(interests[auction_id])
            
            message = {
                "event_type": "new_valid_bid",
                "payload": payload,
                "timestamp": dt_module.datetime.now().isoformat()
            }
            
            for user_id in interested_users:
                self._queue_message(f"user_{user_id}", 'bid_update', message)
            
            logger.info(f"[Notification] Queued new_valid_bid for {len(interested_users)} users")
        except Exception as e:
            logger.error(f"[Notification] Error in notify_new_bid: {e}", exc_info=True)
    
    def notify_invalid_bid(self, payload):
        try:
            user_id = str(payload.get('user_id'))
            message = {
                "event_type": "invalid_bid",
                "payload": payload,
                "timestamp": dt_module.datetime.now().isoformat()
            }
            self._queue_message(f"user_{user_id}", 'bid_error', message)
            logger.info(f"[Notification] Queued invalid_bid for user {user_id}")
        except Exception as e:
            logger.error(f"[Notification] Error in notify_invalid_bid: {e}", exc_info=True)
    
    def notify_auction_started(self, payload):
        try:
            auction_id = str(payload.get('auction_id'))
            with interest_lock:
                if auction_id not in interests:
                    return
                interested_users = list(interests[auction_id])
            
            message = {
                "event_type": "auction_started",
                "payload": payload,
                "timestamp": dt_module.datetime.now().isoformat()
            }
            
            for user_id in interested_users:
                self._queue_message(f"user_{user_id}", 'auction_start', message)
            
            logger.info(f"[Notification] Queued auction_started for {len(interested_users)} users")
        except Exception as e:
            logger.error(f"[Notification] Error in notify_auction_started: {e}", exc_info=True)
    
    def notify_auction_winner(self, payload):
        try:
            auction_id = str(payload.get('auction_id'))
            winner_id = str(payload.get('winner_id'))
            
            with interest_lock:
                if auction_id not in interests:
                    return
                interested_users = list(interests[auction_id])
            
            for user_id in interested_users:
                message = {
                    "event_type": "auction_winner",
                    "payload": {
                        **payload,
                        "is_winner": (user_id == winner_id)
                    },
                    "timestamp": dt_module.datetime.now().isoformat()
                }
                self._queue_message(f"user_{user_id}", 'auction_end', message)
            
            logger.info(f"[Notification] Queued auction_winner for {len(interested_users)} users")
        except Exception as e:
            logger.error(f"[Notification] Error in notify_auction_winner: {e}", exc_info=True)
    
    def notify_payment_link(self, payload):
        try:
            user_id = str(payload.get('customer_id'))
            message = {
                "event_type": "payment_link",
                "payload": payload,
                "timestamp": dt_module.datetime.now().isoformat()
            }
            self._queue_message(f"user_{user_id}", 'payment_info', message)
            logger.info(f"[Notification] Queued payment_link for user {user_id}")
        except Exception as e:
            logger.error(f"[Notification] Error in notify_payment_link: {e}", exc_info=True)
    
    def notify_payment_status(self, payload):
        try:
            user_id = str(payload.get('customer_id'))
            status = payload.get('status')
            message = {
                "event_type": "payment_status",
                "payload": payload,
                "timestamp": dt_module.datetime.now().isoformat()
            }
            self._queue_message(f"user_{user_id}", 'payment_status', message)
            logger.info(f"[Notification] Queued payment_status ({status}) for user {user_id}")
        except Exception as e:
            logger.error(f"[Notification] Error in notify_payment_status: {e}", exc_info=True)

class GatewayCallbackServicer(auction_pb2_grpc.AuctionCallbackServiceServicer):
    def OnAuctionStarted(self, request, context):
        try:
            auction_id = request.auction_id
            start_time = timestamp_to_datetime(request.start_time).isoformat()
            logger.info(f"[Gateway] Auction {auction_id} STARTED (callback received)")
            
            payload = {"auction_id": auction_id, "start_time": start_time}
            notification_manager.notify_auction_started(payload)
            
            return auction_pb2.AuctionEventAck(success=True, message="Notification queued")
        except Exception as e:
            logger.error(f"[Gateway] Error: {e}")
            return auction_pb2.AuctionEventAck(success=False, message=str(e))
    
    def OnAuctionClosed(self, request, context):
        try:
            auction_id = request.auction_id
            has_winner = request.has_winner
            winner_id = request.winner_id
            winning_value = request.winning_value
            end_time = timestamp_to_datetime(request.end_time).isoformat()
            
            logger.info(f"[Gateway] Auction {auction_id} CLOSED (callback received)")
            
            if has_winner:
                payload = {
                    "auction_id": auction_id,
                    "winner_id": winner_id,
                    "value": winning_value,
                    "end_time": end_time
                }
                notification_manager.notify_auction_winner(payload)
            else:
                payload = {
                    "auction_id": auction_id,
                    "has_winner": False,
                    "message": "Auction closed with no bids",
                    "end_time": end_time
                }
                pass 
            
            return auction_pb2.AuctionEventAck(success=True, message="Notification queued")
        except Exception as e:
            logger.error(f"[Gateway] Error: {e}")
            return auction_pb2.AuctionEventAck(success=False, message=str(e))

class BidCallbackServicer(bid_pb2_grpc.BidCallbackServiceServicer):
    def OnPaymentLinkGenerated(self, request, context):
        try:
            auction_id = request.auction_id
            customer_id = request.customer_id
            payment_link = request.payment_link
            transaction_id = request.transaction_id
            status = request.status
            value = request.value
            
            logger.info(f"[Gateway] Payment link received for auction {auction_id}")
            
            payload = {
                "auction_id": auction_id,
                "customer_id": customer_id,
                "payment_link": payment_link,
                "transaction_id": transaction_id,
                "status": status,
                "value": value
            }
            
            notification_manager.notify_payment_link(payload)
            
            return bid_pb2.BidEventAck(
                success=True,
                message="Payment link notification queued"
            )
            
        except Exception as e:
            logger.error(f"[Gateway] Error on payment_link callback: {e}", exc_info=True)
            return bid_pb2.BidEventAck(
                success=False,
                message=str(e)
            )

class GrpcServiceClients:
    def __init__(self):
        self.auction_address = "localhost:50051"
        self.bid_address = "localhost:50052"
        self.auction_channel = None
        self.bid_channel = None
        self.auction_stub = None
        self.bid_stub = None
        self._connect()
    
    def _connect(self):
        try:
            self.auction_channel = grpc.insecure_channel(
                self.auction_address,
                options=[('grpc.keepalive_time_ms', 10000), ('grpc.keepalive_timeout_ms', 5000)]
            )
            self.auction_stub = auction_pb2_grpc.AuctionServiceStub(self.auction_channel)
            
            self.bid_channel = grpc.insecure_channel(
                self.bid_address,
                options=[('grpc.keepalive_time_ms', 10000), ('grpc.keepalive_timeout_ms', 5000)]
            )
            self.bid_stub = bid_pb2_grpc.BidServiceStub(self.bid_channel)
            logger.info("✓ Connected to gRPC services")
        except Exception as e:
            logger.error(f"✗ Error connecting to gRPC services: {e}")
    
    def close(self):
        if self.auction_channel: self.auction_channel.close()
        if self.bid_channel: self.bid_channel.close()

def start_grpc_callback_server(port=50050):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
    auction_pb2_grpc.add_AuctionCallbackServiceServicer_to_server(GatewayCallbackServicer(), server)
    bid_pb2_grpc.add_BidCallbackServiceServicer_to_server(BidCallbackServicer(), server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    logger.info(f"✓ gRPC Callback Server started on port {port}")
    return server

grpc_clients = GrpcServiceClients()
notification_manager = NotificationManager()

@app.route('/api/interest', methods=['POST'])
def register_interest():
    data = request.json
    try:
        auction_id = str(data['auction_id'])
        user_id = str(data['user_id'])
        with interest_lock:
            if auction_id not in interests:
                interests[auction_id] = set()
            interests[auction_id].add(user_id)
        return jsonify({
            "message": f"Interest registered",
            "sse_url": f"/events?channel=user_{user_id}"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/interest', methods=['DELETE'])
def cancel_interest():
    data = request.json
    try:
        auction_id = str(data['auction_id'])
        user_id = str(data['user_id'])
        with interest_lock:
            if auction_id in interests and user_id in interests[auction_id]:
                interests[auction_id].remove(user_id)
                return jsonify({"message": "Interest canceled"}), 200
            else:
                return jsonify({"error": "Interest not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/auction', methods=['GET'])
def get_auctions():
    try:
        grpc_request = auction_pb2.ListAuctionsRequest(filter="all")
        response = grpc_clients.auction_stub.ListAuctions(grpc_request, timeout=5.0)
        auctions = []
        for auction in response.auctions:
            auctions.append({
                "id": auction.id,
                "description": auction.description,
                "start_time": timestamp_to_datetime(auction.start_time).isoformat(),
                "end_time": timestamp_to_datetime(auction.end_time).isoformat(),
                "status": auction.status
            })
        return jsonify(auctions), 200
    except grpc.RpcError as e:
        return jsonify({"error": "Service unavailable"}), 500

@app.route('/api/auction', methods=['POST'])
def create_auction():
    data = request.json
    try:
        start_ts = iso_to_timestamp(data['start_time'])
        end_ts = iso_to_timestamp(data['end_time'])
        grpc_request = auction_pb2.CreateAuctionRequest(
            description=data['description'], start_time=start_ts, end_time=end_ts
        )
        auction = grpc_clients.auction_stub.CreateAuction(grpc_request, timeout=5.0)
        return jsonify({"id": auction.id, "status": auction.status}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/bid', methods=['POST'])
def post_bid():
    data = request.json
    try:
        auction_id = int(data['auction_id'])
        user_id = str(data['user_id'])
        amount = float(data['amount'])
        
        grpc_request = bid_pb2.PlaceBidRequest(
            auction_id=auction_id, user_id=user_id, amount=amount
        )
        response = grpc_clients.bid_stub.PlaceBid(grpc_request, timeout=5.0)
        
        if response.accepted:
            payload = {"auction_id": auction_id, "user_id": user_id, "amount": amount}
            notification_manager.notify_new_bid(payload)
        else:
            payload = {"auction_id": auction_id, "user_id": user_id, 
                       "reason": response.reason, "attempted_amount": amount}
            notification_manager.notify_invalid_bid(payload)
        
        return jsonify({"accepted": response.accepted, "reason": response.reason}), 200 if response.accepted else 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/')
def index():
    return jsonify({"status": "ok", "service": "API Gateway"}), 200

if __name__ == '__main__':
    grpc_callback_server = start_grpc_callback_server(port=50050)

    
    gevent.spawn(sse_worker)
    
    http_server = WSGIServer(('0.0.0.0', 8000), app)
    
    try:
        logger.info("Starting HTTP/SSE server on http://0.0.0.0:8000")
        http_server.serve_forever()
    except KeyboardInterrupt:
        grpc_callback_server.stop(0)
        grpc_clients.close()