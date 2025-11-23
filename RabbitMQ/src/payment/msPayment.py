import json
import threading
import time
import requests
from common.rabbitmq import RabbitMQ
from common.models import Message
from common import config

class MSPayment:
    def __init__(self):
        self.rabbitmq = RabbitMQ()
        self.external_payment_url = "http://localhost:5006/api/payment/create"
        self.webhook_url = "http://localhost:5003/webhook/payment"

    def listen(self):
        def _listen():
            self.rabbitmq.declare_exchange(config.EXCHANGE_NAME, ex_type="direct")
            queue_name = self.rabbitmq.declare_queue("", exclusive=True)
            self.rabbitmq.bind_queue(queue=queue_name, exchange=config.EXCHANGE_NAME, routing_key="leilao_vencedor")
            self.rabbitmq.consume(queue=queue_name, callback=self.handle_event)
        t = threading.Thread(target=_listen, daemon=True)
        t.start()

    def handle_event(self, ch, method, properties, body):
        # Processa evento leilao_vencedor, solicita pagamento externo, publica link de pagamento
        try:
            data = json.loads(body.decode())
            event_type = method.routing_key

            if event_type == "leilao_vencedor":
                self.process_auction_winner(data.get('payload'))

        except Exception as e:
            print(f"[MSPayment] Error processing event: {e}")

    def process_auction_winner(self, payload):
        try:
            payment_payload = {
                "value": payload["value"],
                "currency": "BRL",
                "customer_id": payload["winner_id"],
                "auction_id": payload["auction_id"],
                "webhook_url": self.webhook_url
            }
            response = requests.post(self.external_payment_url, json=payment_payload, timeout=10)
            if response.status_code == 201:
                data = response.json()
                message = Message(
                    event_type="link_pagamento",
                    payload={
                        "auction_id": payload["auction_id"],
                        "customer_id": payload["winner_id"],
                        "payment_link": data["payment_link"],
                        "transaction_id": data["transaction_id"],
                        "status": "created"
                    }
                )
                RabbitMQ().publish(
                    exchange=config.EXCHANGE_NAME,
                    routing_key="link_pagamento",
                    body=message.to_dict()
                )
                print(f"[MSPayment] Payment link ({data['payment_link']}) published for auction {payload['auction_id']}.")
            else:
                print(f"[MSPayment] Failed to create payment: {response.text}")
        except Exception as e:
            print(f"[MSPayment] Error at process_auction_winner: {e}")

    def webhook_server(self):
        from flask import Flask, request, jsonify
        app = Flask(__name__)

        @app.route('/webhook/payment', methods=['POST'])
        def payment_webhook():
            data = request.json
            print(f"[MSPayment] Webhook received: {data}")
            if not data:
                return jsonify({'error': 'Invalid payload'}), 400

            transaction_id = data.get("transaction_id")
            status = data.get("status")
            customer_id = data.get("customer_id")
            auction_id = data.get("auction_id")
            value = data.get("value")

            message = Message(
                event_type="status_pagamento",
                payload={
                    "transaction_id": transaction_id,
                    "auction_id": auction_id,
                    "customer_id": customer_id,
                    "status": status,
                    "value": value
                }
            )
            RabbitMQ().publish(
                exchange=config.EXCHANGE_NAME,
                routing_key="status_pagamento",
                body=message.to_dict()
            )
            return jsonify({"message": "Webhook processed"}), 200

        print("[MSPayment] Starting webhook server on port 5003")
        app.run(debug=True, port=5003, host="0.0.0.0", use_reloader=False)

if __name__ == "__main__":
    mspayment = MSPayment()
    mspayment.listen()
    print("[MSPayment] MSPayment service started and listening for events. Press Ctrl+C to exit.")

    mspayment.webhook_server()
    while True:
        time.sleep(1)
