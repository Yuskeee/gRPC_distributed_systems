import pika
import json
import time
from common import config
from pika.exceptions import AMQPConnectionError

class RabbitMQ:
    def __init__(self, host=config.RABBITMQ_HOST):
        self.host = host
        self.params = pika.ConnectionParameters(
            host=self.host,
            heartbeat=600,
            blocked_connection_timeout=300
        )
        print("Attempting to connect to", self.host)
        self.conn = None
        self.ch = None
        # self.__connect()
        self.__connect_with_retries()

    def __connect_with_retries(self, retries=5, delay=5):
        """Abre a conexão e o canal se ainda não existirem."""
        for attempt in range(retries):
            try:
                if not self.conn or self.conn.is_closed:
                    self.conn = pika.BlockingConnection(self.params)
                    print("[RabbitMQ] Connected successfully")
                    self.ch = self.conn.channel()
                return self.conn, self.ch
            except AMQPConnectionError as e:
                print(f"[RabbitMQ] Connection attempt {attempt+1} failed: {e}")
                time.sleep(delay)
        raise AMQPConnectionError(f"Could not connect to RabbitMQ after {retries} attempts")
    
    def __connect(self):
        """Abre a conexão e o canal se ainda não existirem."""
        if not self.conn or self.conn.is_closed:
            self.conn = pika.BlockingConnection(self.params)
            self.ch = self.conn.channel()
        return self.conn, self.ch

    def declare_exchange(self, exchange: str, ex_type="direct", durable=True):
        """Declara um exchange persistente."""
        _, ch = self.__connect_with_retries()
        ch.exchange_declare(exchange=exchange, exchange_type=ex_type, durable=durable)

    def declare_queue(self, queue: str = "", exclusive=False, durable=True):
        """
        Declara uma fila. 
        Se `queue=""` -> RabbitMQ cria uma fila temporária com nome aleatório (ex: amq.gen-...).
        """
        _, ch = self.__connect_with_retries()
        result = ch.queue_declare(queue=queue, exclusive=exclusive, durable=durable)
        return result.method.queue

    def bind_queue(self, queue: str, exchange: str, routing_key: str):
        """Faz o bind de uma fila a um exchange com uma routing_key."""
        _, ch = self.__connect_with_retries()
        ch.queue_bind(exchange=exchange, queue=queue, routing_key=routing_key)

    def publish(self, exchange: str, routing_key: str, body: dict):
        """Publica uma mensagem JSON no exchange."""
        _, ch = self.__connect_with_retries()
        ch.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=json.dumps(body),
            properties=pika.BasicProperties(delivery_mode=2)  # mensagem persistente
        )

    def consume(self, queue: str, callback, auto_ack=True):
        """Consome mensagens de uma fila usando callback."""
        _, ch = self.__connect_with_retries()
        ch.basic_consume(queue=queue, on_message_callback=callback, auto_ack=auto_ack)
        print(f"[i] Aguardando mensagens na fila '{queue}'...")
        try:
            ch.start_consuming()
        except KeyboardInterrupt:
            ch.stop_consuming()

    def close(self):
        """Fecha conexão limpa."""
        if self.conn and not self.conn.is_closed:
            self.conn.close()
