# from flask import Flask, request, jsonify, Response
# import threading
# import time
# import json
# import requests

# from notification import MSNotification
# from common.models import Auction, Bid, Message
# from common.rabbitmq import RabbitMQ
# from common.config import EXCHANGE_NAME
# from sse import app as sse_app, SSE

# # ---- Configuração URLs dos microsserviços ----
# MS_AUCTION_URL = "http://host.docker.internal:5004"
# MS_BID_URL = "http://host.docker.internal:5005"

# app = Flask(__name__)
# rabbitmq = RabbitMQ()
# exchange = EXCHANGE_NAME

# # ------ Tracking de interesse ------
# interests = {}  # {auction_id: set(user_id)}

# @app.route('/api/interest', methods=['POST'])
# def register_interest():
#     """
#     REST endpoint to register user interest in an auction.
#     Body JSON: { "auction_id": ..., "user_id": ... }
#     """
#     data = request.json
#     try:
#         auction_id = str(data['auction_id'])
#         user_id = str(data['user_id'])
#         if auction_id not in interests:
#             interests[auction_id] = set()
#         interests[auction_id].add(user_id)
#         return jsonify({"message": f"Interest registered for auction {auction_id} by user {user_id}."}), 200
#     except Exception as e:
#         return jsonify({"error": f"Invalid data: {str(e)}"}), 400

# @app.route('/api/interest', methods=['DELETE'])
# def cancel_interest():
#     """
#     REST endpoint to cancel user interest in an auction.
#     Body JSON: { "auction_id": ..., "user_id": ... }
#     """
#     data = request.json
#     try:
#         auction_id = str(data['auction_id'])
#         user_id = str(data['user_id'])
#         if auction_id in interests and user_id in interests[auction_id]:
#             interests[auction_id].remove(user_id)
#             return jsonify({"message": f"Interest canceled for auction {auction_id} by user {user_id}."}), 200
#         else:
#             return jsonify({"error": "Interest not found."}), 404
#     except Exception as e:
#         return jsonify({"error": f"Invalid data: {str(e)}"}), 400

# @app.route('/api/interest', methods=['GET'])
# def list_interests():
#     """List interests (debug purposes)"""
#     return jsonify({k: list(v) for k, v in interests.items()}), 200

# # ---- Auction REST endpoints ----
# @app.route('/api/auction', methods=['GET'])
# def get_auctions():
#     try:
#         response = requests.get(f"{MS_AUCTION_URL}/api/auction")
#         return jsonify(response.json()), response.status_code
#     except Exception as e:
#         return jsonify({"error": f"Error contacting auction service: {str(e)}"}), 500

# @app.route('/api/auction', methods=['POST'])
# def create_auction():
#     data = request.json
#     try:
#         response = requests.post(f"{MS_AUCTION_URL}/api/auction", json=data)
#         return jsonify(response.json()), response.status_code
#     except Exception as e:
#         return jsonify({"error": f"Error contacting auction service: {str(e)}"}), 500

# # ---- Bid REST endpoint ----
# @app.route('/api/bid', methods=['POST'])
# def post_bid():
#     data = request.json
#     try:
#         response = requests.post(f"{MS_BID_URL}/api/bid", json=data)
#         return jsonify(response.json()), response.status_code
#     except Exception as e:
#         return jsonify({"error": f"Error contacting bid service: {str(e)}"}), 500

# # ---- SSE (Server-Side Events) ----
# @app.route('/events')
# def sse_auction():
#     """
#     SSE endpoint.
#     """
#     # O notification.py já faz o forward dos eventos para o SSE
#     return sse_app.full_dispatch_request()

# # ---- Startup ----
# def start_notification_listener():
#     notification_service = MSNotification()
#     notification_service.listen()

# if __name__ == '__main__':
#     threading.Thread(target=start_notification_listener, daemon=True).start()
#     app.run(debug=True, host='0.0.0.0', port=8000)

from flask import Flask, request, jsonify, abort
from flask_sse import sse
from flask_cors import CORS
import time
import json
import datetime
import requests
import logging
import os
from gevent import monkey, spawn
from gevent.event import Event


# Tava dando ruim misturar PIKA com Gevent com REST sem isso
monkey.patch_all(thread=False)


from common.models import Auction, Bid, Message
from common.rabbitmq import RabbitMQ
from common.config import EXCHANGE_NAME


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


MS_AUCTION_URL = os.environ.get("MS_AUCTION_URL", "http://host.docker.internal:5004")
MS_BID_URL = os.environ.get("MS_BID_URL", "http://host.docker.internal:5005")


rabbitmq = RabbitMQ()
exchange = EXCHANGE_NAME


interests = {}  # {auction_id: set(user_id)}

class Notification:
    def __init__(self):
        self.exchange = EXCHANGE_NAME
        self.rabbitmq = RabbitMQ()
        self.keep_alive_interval = 30
        self.running = Event()


    def listen(self):
        """Inicia o listener do RabbitMQ usando gevent spawn"""
        def _listen():
            try:
                logger.info("[Notification] Initializing RabbitMQ listener...")
                self.rabbitmq.declare_exchange(self.exchange, ex_type="direct")
                queue_name = self.rabbitmq.declare_queue("", exclusive=True)
                
                # Bind das routing keys
                routing_keys = [
                    "lance_validado",
                    "lance_invalidado",
                    "leilao_vencedor",
                    "link_pagamento",
                    "status_pagamento"
                ]
                
                for routing_key in routing_keys:
                    self.rabbitmq.bind_queue(
                        queue=queue_name,
                        exchange=self.exchange,
                        routing_key=routing_key
                    )
                    logger.info(f"[Notification] Bound to routing key: {routing_key}")
                
                logger.info("[Notification] Starting to consume messages...")
                self.running.set()
                self.rabbitmq.consume(queue=queue_name, callback=self.handle_event)
            except Exception as e:
                logger.error(f"[Notification] Error in listener: {e}", exc_info=True)
        
        spawn(_listen)
        logger.info("[Notification] Listener spawned")


    def start_keep_alive(self):
        """Envia mensagens keep-alive periódicas usando gevent"""
        def _send_keep_alive():
            self.running.wait(timeout=5)
            logger.info("[Notification] Keep-alive thread started")
            
            while True:
                try:
                    time.sleep(self.keep_alive_interval)
                    keep_alive_message = {
                        "event_type": "keepalive",
                        "payload": {"status": "alive"},
                        "timestamp": datetime.datetime.now().isoformat()
                    }
                    
                    # Enviar keep-alive para todos os usuários/canaias
                    with app.app_context():
                        sse.publish(keep_alive_message, type='keepalive')
                    
                    logger.debug(f"[Notification] Keep-alive sent to all channels")
                except Exception as e:
                    logger.error(f"[Notification] Error sending keep-alive: {e}")
        
        spawn(_send_keep_alive)


    def handle_event(self, ch, method, properties, body):
        """Processa eventos recebidos do RabbitMQ e roteia para canais específicos"""
        try:
            data = json.loads(body.decode())
            event_type = method.routing_key
            payload = data.get("payload", {})
            
            logger.info(f"[Notification] Received event: {event_type}")
            
            # Rotear evento para os canais apropriados
            if event_type == "lance_validado":
                self.notify_new_bid(payload)
            elif event_type == "lance_invalidado":
                self.notify_invalid_bid(payload)
            elif event_type == "leilao_vencedor":
                self.notify_auction_winner(payload)
            elif event_type == "link_pagamento":
                self.notify_payment_link(payload)
            elif event_type == "status_pagamento":
                self.notify_payment_status(payload)
                
        except Exception as e:
            logger.error(f"[Notification] Error processing event: {e}", exc_info=True)


    def notify_new_bid(self, payload):
        """
        Notifica novo lance válido apenas aos clientes registrados no leilão.
        """
        try:
            auction_id = str(payload.get('auction_id'))
            
            if auction_id not in interests:
                logger.info(f"[Notification] No interested users for auction {auction_id}")
                return
            
            interested_users = interests[auction_id]
            message = {
                "event_type": "new_valid_bid",
                "payload": payload,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            # Enviar para cada usuário interessado
            with app.app_context():
                for user_id in interested_users:
                    channel = f"user_{user_id}"
                    sse.publish(message, type='bid_update', channel=channel)
                
                logger.info(f"[Notification] Sent new_valid_bid to {len(interested_users)} users")
                    
        except Exception as e:
            logger.error(f"[Notification] Error in notify_new_bid: {e}", exc_info=True)


    def notify_invalid_bid(self, payload):
        """
        Notifica lance inválido apenas ao usuário que fez o lance.
        """
        try:
            user_id = str(payload.get('user_id'))
            
            message = {
                "event_type": "invalid_bid",
                "payload": payload,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            # Enviar apenas para o usuário que fez o lance
            with app.app_context():
                channel = f"user_{user_id}"
                sse.publish(message, type='bid_error', channel=channel)
                logger.info(f"[Notification] Sent invalid_bid to user {user_id}")
                
        except Exception as e:
            logger.error(f"[Notification] Error in notify_invalid_bid: {e}", exc_info=True)


    def notify_auction_winner(self, payload):
        """
        Notifica vencedor do leilão aos clientes registrados.
        """
        try:
            auction_id = str(payload.get('auction_id'))
            winner_id = str(payload.get('winner_id'))
            
            if auction_id not in interests:
                logger.info(f"[Notification] No interested users for auction {auction_id}")
                return
            
            interested_users = interests[auction_id]
            
            # Enviar para cada usuário interessado
            with app.app_context():
                for user_id in interested_users:
                    channel = f"user_{user_id}"
                    
                    # Personalizar mensagem se for o vencedor
                    message = {
                        "event_type": "auction_winner",
                        "payload": {
                            **payload,
                            "is_winner": (user_id == winner_id)
                        },
                        "timestamp": datetime.datetime.now().isoformat()
                    }
                    
                    sse.publish(message, type='auction_end', channel=channel)
                
                logger.info(f"[Notification] Sent auction_winner to {len(interested_users)} users")
                    
        except Exception as e:
            logger.error(f"[Notification] Error in notify_auction_winner: {e}", exc_info=True)


    def notify_payment_link(self, payload):
        """
        Notifica link de pagamento apenas ao vencedor do leilão.
        """
        try:
            user_id = str(payload.get('customer_id'))
            
            message = {
                "event_type": "payment_link",
                "payload": payload,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            # Enviar apenas para o usuário vencedor
            with app.app_context():
                channel = f"user_{user_id}"
                sse.publish(message, type='payment_info', channel=channel)
                logger.info(f"[Notification] Sent payment_link to user {user_id}")
                
        except Exception as e:
            logger.error(f"[Notification] Error in notify_payment_link: {e}", exc_info=True)


    def notify_payment_status(self, payload):
        """
        Notifica status do pagamento (aprovado/recusado) ao usuário.
        """
        try:
            user_id = str(payload.get('customer_id'))
            status = payload.get('status')  # 'approved' ou 'rejected'
            
            message = {
                "event_type": "payment_status",
                "payload": payload,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            # Enviar apenas para o usuário que está pagando
            with app.app_context():
                channel = f"user_{user_id}"
                sse.publish(message, type='payment_status', channel=channel)
                logger.info(f"[Notification] Sent payment_status ({status}) to user {user_id}")
                
        except Exception as e:
            logger.error(f"[Notification] Error in notify_payment_status: {e}", exc_info=True)

@app.route('/api/interest', methods=['POST'])
def register_interest():
    """
    Registra interesse de um usuário em um leilão.
    Body JSON: { "auction_id": "123", "user_id": "user456" }
    """
    data = request.json
    try:
        auction_id = str(data['auction_id'])
        user_id = str(data['user_id'])
        
        if auction_id not in interests:
            interests[auction_id] = set()
        interests[auction_id].add(user_id)
        
        logger.info(f"Interest registered: auction={auction_id}, user={user_id}")
        return jsonify({
            "message": f"Interest registered for auction {auction_id} by user {user_id}.",
            "sse_channel": f"user_{user_id}",
            "sse_url": f"/events?channel=user_{user_id}"
        }), 200
    except Exception as e:
        logger.error(f"Error registering interest: {e}")
        return jsonify({"error": f"Invalid data: {str(e)}"}), 400


@app.route('/api/interest', methods=['DELETE'])
def cancel_interest():
    """
    Cancela interesse de um usuário em um leilão.
    Body JSON: { "auction_id": "123", "user_id": "user456" }
    """
    data = request.json
    try:
        auction_id = str(data['auction_id'])
        user_id = str(data['user_id'])
        
        if auction_id in interests and user_id in interests[auction_id]:
            interests[auction_id].remove(user_id)
            logger.info(f"Interest canceled: auction={auction_id}, user={user_id}")
            return jsonify({
                "message": f"Interest canceled for auction {auction_id} by user {user_id}."
            }), 200
        else:
            return jsonify({"error": "Interest not found."}), 404
    except Exception as e:
        logger.error(f"Error canceling interest: {e}")
        return jsonify({"error": f"Invalid data: {str(e)}"}), 400


@app.route('/api/interest', methods=['GET'])
def list_interests():
    """Lista todos os interesses"""
    return jsonify({k: list(v) for k, v in interests.items()}), 200

@app.route('/api/auction', methods=['GET'])
def get_auctions():
    """Obtém lista de leilões"""
    try:
        response = requests.get(f"{MS_AUCTION_URL}/api/auction", timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.exceptions.RequestException as e:
        logger.error(f"Error contacting auction service: {e}")
        return jsonify({"error": f"Error contacting auction service: {str(e)}"}), 500


@app.route('/api/auction', methods=['POST'])
def create_auction():
    """Cria novo leilão"""
    data = request.json
    try:
        response = requests.post(f"{MS_AUCTION_URL}/api/auction", json=data, timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.exceptions.RequestException as e:
        logger.error(f"Error contacting auction service: {e}")
        return jsonify({"error": f"Error contacting auction service: {str(e)}"}), 500

@app.route('/api/bid', methods=['POST'])
def post_bid():
    """Registra novo lance"""
    data = request.json
    try:
        response = requests.post(f"{MS_BID_URL}/api/bid", json=data, timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.exceptions.RequestException as e:
        logger.error(f"Error contacting bid service: {e}")
        return jsonify({"error": f"Error contacting bid service: {str(e)}"}), 500

@app.route('/')
def index():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "service": "API Gateway",
        "version": "1.0.0",
        "timestamp": datetime.datetime.now().isoformat()
    }), 200

@app.route('/health')
def health():
    """Detailed health check"""
    return jsonify({
        "status": "healthy",
        "redis": app.config["REDIS_URL"],
        "rabbitmq": "connected",
        "interests": len(interests),
        "active_auctions": len(interests)
    }), 200




notification_service = Notification()
notification_service.listen()
notification_service.start_keep_alive()
logger.info("=" * 60)
logger.info("API GATEWAY INITIALIZED")
logger.info("=" * 60)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
