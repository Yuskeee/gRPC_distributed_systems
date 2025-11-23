import time
import sched
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from common.rabbitmq import RabbitMQ
from common.models import Auction, Message
from common import config

app = Flask(__name__)

auctions = [
    # Auction(
    #     id=1,
    #     description="Notebook Gamer",
    #     start_time=datetime.now() + timedelta(seconds=10),
    #     end_time=datetime.now() + timedelta(seconds=600),
    #     status="pending"
    # ),
    # Auction(
    #     id=2,
    #     description="Smartphone Novo",
    #     start_time=datetime.now() + timedelta(seconds=20),
    #     end_time=datetime.now() + timedelta(seconds=800),
    #     status="pending"
    # ),
]

def check_auctions_job(sc, rabbitmq_instance):
    """
    Função de trabalho que verifica o estado dos leilões e se re-agenda.
    """
    now = datetime.now()
    for auction in auctions:
        # Start auction if time is reached
        if auction.status == "pending" and now >= auction.start_time:
            auction.status = "active"
            message = Message(event_type="leilao_iniciado", payload=auction.to_dict())
            rabbitmq_instance.publish(exchange=config.EXCHANGE_NAME, routing_key="leilao_iniciado", body=message.to_dict())
            print(f"Auction {auction.id} ({auction.description}) started.")
        # End auction if time expired
        elif auction.status == "active" and now >= auction.end_time:
            auction.status = "closed"
            message = Message(event_type="leilao_finalizado", payload=auction.to_dict())
            rabbitmq_instance.publish(exchange=config.EXCHANGE_NAME, routing_key="leilao_finalizado", body=message.to_dict())
            print(f"Auction {auction.id} ({auction.description}) finished.")
    sc.enter(1, 1, check_auctions_job, (sc, rabbitmq_instance))

@app.route('/api/auction', methods=['GET'])
def list_auctions():
    """
    REST endpoint: list auctions
    """
    return jsonify([a.to_dict() for a in auctions]), 200

@app.route('/api/auction', methods=['POST'])
def create_auction():
    """
    REST endpoint: create auction
    """
    data = request.json
    au_id = len(auctions) + 1
    auction = Auction(
        id=au_id,
        description=data['description'],
        start_time=datetime.fromisoformat(data['start_time']),
        end_time=datetime.fromisoformat(data['end_time']),
        status='pending'
    )
    auctions.append(auction)
    return jsonify(auction.to_dict()), 201

def main():
    """
    Função principal do microsserviço de Leilão.
    """
    rabbitmq = RabbitMQ()
    rabbitmq.declare_exchange(config.EXCHANGE_NAME, ex_type='direct')
    scheduler = sched.scheduler(time.time, time.sleep)
    print("Auction microservice started.")
    try:
        scheduler.enter(1, 1, check_auctions_job, (scheduler, rabbitmq))
        # Rodando Flask e scheduler em threads separados
        import threading
        flask_thread = threading.Thread(target=lambda: app.run(debug=True, port=5004, host="0.0.0.0", use_reloader=False))
        flask_thread.start()
        scheduler.run()
    except KeyboardInterrupt:
        print("\nAuction microservice stopped.")

if __name__ == '__main__':
    main()
