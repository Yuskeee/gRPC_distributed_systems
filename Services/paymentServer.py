import grpc
from concurrent import futures
import requests
import json
import threading
from flask import Flask, request, jsonify
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../grpcFiles')))

import payment_pb2
import payment_pb2_grpc

class PaymentServicer(payment_pb2_grpc.PaymentServiceServicer):
    def __init__(self):
        self.external_payment_url = "http://localhost:5006/api/payment/create"
        self.webhook_url = "http://localhost:5003/webhook/payment"
        
        self.payments = {}
        
        self.notification_callbacks = []
        
    def ProcessAuctionWinner(self, request, context):
        try:
            print(f"[PaymentServer] Processing auction winner: "
                  f"auction_id={request.auction_id}, winner={request.winner_id}, "
                  f"value={request.value}")
            
            payment_payload = {
                "value": request.value,
                "currency": request.currency if request.currency else "BRL",
                "customer_id": request.winner_id,
                "auction_id": request.auction_id,
                "webhook_url": self.webhook_url
            }
            
            response = requests.post(
                self.external_payment_url, 
                json=payment_payload, 
                timeout=10
            )
            
            if response.status_code == 201:
                data = response.json()
                
                transaction_id = data["transaction_id"]
                self.payments[transaction_id] = {
                    "auction_id": request.auction_id,
                    "customer_id": request.winner_id,
                    "payment_link": data["payment_link"],
                    "transaction_id": transaction_id,
                    "status": "created",
                    "value": request.value
                }
                
                print(f"[PaymentServer] Payment link created: {data['payment_link']} "
                      f"for auction {request.auction_id}")
                
                return payment_pb2.PaymentLinkResponse(
                    success=True,
                    message="Payment link created successfully",
                    auction_id=request.auction_id,
                    customer_id=request.winner_id,
                    payment_link=data["payment_link"],
                    transaction_id=transaction_id,
                    status="created"
                )
            else:
                error_msg = f"External payment service failed: {response.text}"
                print(f"[PaymentServer] {error_msg}")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(error_msg)
                return payment_pb2.PaymentLinkResponse(
                    success=False,
                    message=error_msg
                )
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Error calling external payment service: {str(e)}"
            print(f"[PaymentServer] {error_msg}")
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(error_msg)
            return payment_pb2.PaymentLinkResponse(
                success=False,
                message=error_msg
            )
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            print(f"[PaymentServer] {error_msg}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(error_msg)
            return payment_pb2.PaymentLinkResponse(
                success=False,
                message=error_msg
            )
    
    def UpdatePaymentStatus(self, request, context):
        try:
            print(f"[PaymentServer] Updating payment status: "
                  f"transaction_id={request.transaction_id}, status={request.status}")
            
            if request.transaction_id in self.payments:
                self.payments[request.transaction_id]["status"] = request.status
            else:
                self.payments[request.transaction_id] = {
                    "transaction_id": request.transaction_id,
                    "auction_id": request.auction_id,
                    "customer_id": request.customer_id,
                    "status": request.status,
                    "value": request.value
                }
            
            self._notify_payment_status_change(request)
            
            return payment_pb2.PaymentStatusAck(
                success=True,
                message="Payment status updated successfully"
            )
            
        except Exception as e:
            error_msg = f"Error updating payment status: {str(e)}"
            print(f"[PaymentServer] {error_msg}")
            return payment_pb2.PaymentStatusAck(
                success=False,
                message=error_msg
            )
    
    def GetPaymentStatus(self, request, context):
        try:
            transaction_id = request.transaction_id
            
            if transaction_id in self.payments:
                payment = self.payments[transaction_id]
                return payment_pb2.PaymentQueryResponse(
                    found=True,
                    transaction_id=transaction_id,
                    auction_id=payment.get("auction_id", 0),
                    customer_id=payment.get("customer_id", ""),
                    status=payment.get("status", "unknown"),
                    value=payment.get("value", 0.0),
                    payment_link=payment.get("payment_link", "")
                )
            else:
                return payment_pb2.PaymentQueryResponse(
                    found=False,
                    transaction_id=transaction_id
                )
                
        except Exception as e:
            print(f"[PaymentServer] Error querying payment: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return payment_pb2.PaymentQueryResponse(found=False)
    
    def _notify_payment_status_change(self, payment_update):
        pass


class PaymentServer:
    def __init__(self, port=5003, grpc_port=50053):
        self.port = port
        self.grpc_port = grpc_port
        self.servicer = PaymentServicer()
        self.grpc_server = None
        
    def start_grpc_server(self):
        """Start the gRPC server"""
        self.grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        payment_pb2_grpc.add_PaymentServiceServicer_to_server(
            self.servicer, 
            self.grpc_server
        )
        self.grpc_server.add_insecure_port(f'[::]:{self.grpc_port}')
        self.grpc_server.start()
        print(f"[PaymentServer] gRPC server started on port {self.grpc_port}")
        
    def start_webhook_server(self):
        app = Flask(__name__)
        
        @app.route('/webhook/payment', methods=['POST'])
        def payment_webhook():
            data = request.json
            print(f"[PaymentServer] Webhook received: {data}")
            
            if not data:
                return jsonify({'error': 'Invalid payload'}), 400
            
            try:
                status_update = payment_pb2.PaymentStatusUpdate(
                    transaction_id=data.get("transaction_id", ""),
                    auction_id=data.get("auction_id", 0),
                    customer_id=data.get("customer_id", ""),
                    status=data.get("status", "unknown"),
                    value=data.get("value", 0.0)
                )
                
                response = self.servicer.UpdatePaymentStatus(status_update, None)
                
                if response.success:
                    return jsonify({"message": "Webhook processed"}), 200
                else:
                    return jsonify({"error": response.message}), 500
                    
            except Exception as e:
                print(f"[PaymentServer] Error processing webhook: {e}")
                return jsonify({"error": str(e)}), 500
        
        @app.route('/health', methods=['GET'])
        def health():
            return jsonify({"status": "healthy", "service": "PaymentServer"}), 200
        
        print(f"[PaymentServer] Starting webhook server on port {self.port}")
        app.run(debug=False, port=self.port, host="0.0.0.0", use_reloader=False)
    
    def serve(self):
        self.start_grpc_server()
        
        webhook_thread = threading.Thread(
            target=self.start_webhook_server, 
            daemon=True
        )
        webhook_thread.start()
        
        print("[PaymentServer] Payment service is running. Press Ctrl+C to exit.")
        
        try:
            self.grpc_server.wait_for_termination()
        except KeyboardInterrupt:
            print("\n[PaymentServer] Shutting down...")
            self.grpc_server.stop(0)


if __name__ == "__main__":
    server = PaymentServer(port=5003, grpc_port=50053)
    server.serve()
