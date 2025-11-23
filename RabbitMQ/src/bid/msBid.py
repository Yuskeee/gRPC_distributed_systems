import json
import threading
import time
from flask import Flask, request, jsonify
from common.rabbitmq import RabbitMQ
from common.models import Bid, Message
from common import config

app = Flask(__name__)

class MSBid:
    def __init__(self):
        self.rabbitmq = RabbitMQ()
        self.highest_bids = {}
        self.auction_status = {}

    def listen(self):
        def _listen():
            self.rabbitmq.declare_exchange(config.EXCHANGE_NAME, ex_type="direct")
            queue_name = self.rabbitmq.declare_queue("", exclusive=True)
            for routing_key in ["leilao_iniciado", "leilao_finalizado"]:
                self.rabbitmq.bind_queue(queue=queue_name, exchange=config.EXCHANGE_NAME, routing_key=routing_key)
            self.rabbitmq.consume(queue=queue_name, callback=self.handle_event)
        t = threading.Thread(target=_listen, daemon=True)
        t.start()

    def handle_event(self, ch, method, properties, body):
        try:
            data = json.loads(body.decode())
            event_type = method.routing_key
            if event_type == "leilao_iniciado":
                self.process_auction_started(data.get('payload'))
            elif event_type == "leilao_finalizado":
                self.process_auction_closed(data.get('payload'))
        except Exception as e:
            print(f"[MSBid] Error processing event: {e}")

    def process_auction_started(self, payload):
        try:
            auction_id = payload['id']
            self.auction_status[auction_id] = "active"
            self.highest_bids[auction_id] = None
            print(f"[MSBid] Auction {auction_id} started.")
        except Exception as e:
            print(f"[MSBid] Error on auction_started: {e}")

    def process_auction_closed(self, payload):
        try:
            auction_id = payload['id']
            self.auction_status[auction_id] = "closed"
            winner_info = self.highest_bids.get(auction_id)
            if winner_info:
                message = Message(event_type="leilao_vencedor", payload={
                    "auction_id": auction_id,
                    "winner_id": winner_info['user_id'],
                    "value": winner_info['amount']
                })
                RabbitMQ().publish(exchange=config.EXCHANGE_NAME, routing_key="leilao_vencedor", body=message.to_dict())
                print(f"[MSBid] Auction {auction_id} closed! Winner: {winner_info['user_id'][:8]}..., Value: {winner_info['amount']:.2f}")
            else:
                print(f"[MSBid] Auction {auction_id} closed. No valid bids.")
        except Exception as e:
            print(f"[MSBid] Error on auction_closed: {e}")

    def process_bid(self, bid_data):
        try:
            user_id = bid_data['user_id']
            auction_id = int(bid_data['auction_id'])
            amount = bid_data['amount']
            print(f"[MSBid] Bid received: user {user_id[:8]}..., auction {auction_id}, value {amount:.2f}")
            # 1. Auction must exist and be active
            if self.auction_status.get(auction_id) != "active":
                print("[MSBid] Auction is not active. Ignoring bid.")
                return
            # 2. Bid must be higher than current max
            current = self.highest_bids.get(auction_id)
            if current and amount <= current['amount']:
                print("[MSBid] Bid not higher than current maximum. Ignoring bid.")
                message = Message(event_type="lance_invalidado", payload={
                    "auction_id": auction_id,
                    "user_id": user_id,
                    "amount": amount
                })
                RabbitMQ().publish(exchange=config.EXCHANGE_NAME, routing_key="lance_invalidado", body=message.to_dict())
                print(f"[MSBid] Ignored bid for auction {auction_id}: {amount:.2f} by user {user_id[:8]}...")
                return
            # Accept bid
            self.highest_bids[auction_id] = {'user_id': user_id, 'amount': amount}
            # Notify
            message = Message(event_type="lance_validado", payload={
                "auction_id": auction_id,
                "user_id": user_id,
                "amount": amount
            })
            RabbitMQ().publish(exchange=config.EXCHANGE_NAME, routing_key="lance_validado", body=message.to_dict())
            print(f"[MSBid] New highest bid for auction {auction_id}: {amount:.2f} by user {user_id[:8]}...")
        except Exception as e:
            print(f"[MSBid] Error processing bid: {e}")

msbid = MSBid()
msbid.listen()

@app.route('/api/bid', methods=['POST'])
def place_bid():
    try:
        data = request.json
        bid = Bid(auction_id=data['auction_id'], user_id=data['user_id'], amount=data['amount'])
        msbid.process_bid(bid.to_dict())
        return jsonify({"message": "Bid placed!"}), 202
    except Exception as e:
        import traceback
        print("Bid error:", traceback.format_exc())
        return jsonify({"error": f"Failed to place bid: {str(e)}"}), 400

if __name__ == "__main__":
    print("[MSBid] MSBid service started and listening for events.\nPress Ctrl+C to exit.")
    flask_thread = threading.Thread(target=lambda: app.run(debug=True, port=5005, host="0.0.0.0", use_reloader=False))
    flask_thread.start()
    while True:
        time.sleep(1)
