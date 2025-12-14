from flask import Flask, request, jsonify
import requests
import uuid
import random
import threading
import time


app = Flask(__name__)


# Simula um banco de dados de transações
transactions = {}

@app.route('/api/payment/create', methods=['POST'])
def create_payment():
    """
    Recebe requisição REST do MS Pagamento para criar um link de pagamento.
    Payload esperado: {value, currency, customer_id, auction_id}
    """
    data = request.json
    
    # Validação básica
    if not data or 'value' not in data or 'customer_id' not in data:
        return jsonify({'error': 'Invalid data'}), 400
    
    # Gera ID único para a transação
    transaction_id = str(uuid.uuid4())
    
    # Cria o link de pagamento simulado
    payment_link = f"http://localhost:5006/payment/{transaction_id}"
    
    # Armazena transação
    transactions[transaction_id] = {
        'id': transaction_id,
        'value': data['value'],
        'currency': data.get('currency', 'BRL'),
        'customer_id': data['customer_id'],
        'auction_id': data.get('auction_id'),
        'status': 'pending',
        'webhook_url': data.get('webhook_url')
    }
    
    print(f"[Sistema Pagamento] Transação criada: {transaction_id}")
    
    # Retorna o link de pagamento
    return jsonify({
        'transaction_id': transaction_id,
        'payment_link': payment_link,
        'status': 'created'
    }), 201


@app.route('/payment/<transaction_id>', methods=['GET'])
def display_payment(transaction_id):
    """
    Página que o cliente acessa para visualizar os detalhes do pagamento
    """
    if transaction_id not in transactions:
        return "Transaction not found", 404
    
    transaction = transactions[transaction_id]
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Payment - External System</title>
        <style>
            body {{ font-family: Arial; max-width: 500px; margin: 50px auto; padding: 20px; }}
            .card {{ border: 1px solid #ccc; padding: 20px; border-radius: 8px; }}
            button {{ background-color: #4CAF50; color: white; padding: 10px 20px; 
                     border: none; border-radius: 4px; cursor: pointer; margin: 5px; }}
            button.cancel {{ background-color: #f44336; }}
            .info {{ margin: 10px 0; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Payment Confirmation</h2>
            <div class="info"><strong>Transaction ID:</strong> {transaction_id}</div>
            <div class="info"><strong>Value:</strong> {transaction['currency']} {transaction['value']:.2f}</div>
            <div class="info"><strong>Status:</strong> {transaction['status']}</div>
            <br>
            <button onclick="processPayment('approved')">Approve Payment</button>
            <button class="cancel" onclick="processPayment('declined')">Decline Payment</button>
        </div>
        
        <script>
            function processPayment(status) {{
                fetch('/payment/{transaction_id}/process', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{status: status}})
                }})
                .then(response => response.json())
                .then(data => {{
                    alert('Payment ' + status + '!');
                    window.location.reload();
                }});
            }}
        </script>
    </body>
    </html>
    """
    return html


@app.route('/payment/<transaction_id>/process', methods=['POST'])
def process_payment(transaction_id):
    """
    Processa o pagamento e envia webhook para o MS Pagamento
    """
    if transaction_id not in transactions:
        return jsonify({'error': 'Transaction not found'}), 404
    
    data = request.json
    status = data.get('status', 'approved')
    
    transaction = transactions[transaction_id]
    transaction['status'] = status
    
    # Envia webhook de forma assíncrona
    if transaction.get('webhook_url'):
        threading.Thread(
            target=send_webhook,
            args=(transaction['webhook_url'], transaction_id, status, transaction)
        ).start()
    
    return jsonify({
        'transaction_id': transaction_id,
        'status': status
    })


def send_webhook(webhook_url, transaction_id, status, transaction):
    """
    Envia notificação assíncrona via webhook (HTTP POST)
    """
    time.sleep(2)  # Simula processamento
    
    payload = {
        'transaction_id': transaction_id,
        'status': status,
        'value': transaction['value'],
        'currency': transaction['currency'],
        'customer_id': transaction['customer_id'],
        'auction_id': transaction.get('auction_id'),
        'timestamp': time.time()
    }
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        print(f"[Sistema Pagamento] Webhook enviado: {status} - Status Code: {response.status_code}")
    except Exception as e:
        print(f"[Sistema Pagamento] Erro ao enviar webhook: {e}")


if __name__ == '__main__':
    print("[Sistema Pagamento Externo] Iniciando na porta 5006...")
    app.run(debug=True, port=5006, host='0.0.0.0')
