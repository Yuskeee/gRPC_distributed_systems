import uuid
import time
import os
import sys

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from auction import auction_pb2, auction_pb2_grpc
from bid import bid_pb2, bid_pb2_grpc


class AuctionClient:
    def __init__(self, auction_target: str = "localhost:50051", bid_target: str = "localhost:50052"):
        self.user_id = str(uuid.uuid4())

        self.auction_channel = grpc.insecure_channel(auction_target)
        self.bid_channel = grpc.insecure_channel(bid_target)

        self.auction_stub = auction_pb2_grpc.AuctionServiceStub(self.auction_channel)
        self.bid_stub = bid_pb2_grpc.BidServiceStub(self.bid_channel)

    def list_auctions(self):
        resp = self.auction_stub.ListAuctions(auction_pb2.ListAuctionsRequest())
        if not resp.auctions:
            print("Nenhum leilão disponível.")
            return

        print("\n--- Leilões ---")
        now = int(time.time())
        for a in resp.auctions:
            status = a.status
            start_ts = a.start_time.seconds
            end_ts = a.end_time.seconds
            print(
                f"ID: {a.id}, Descrição: {a.description}, "
                f"Início: {start_ts}, Fim: {end_ts}, Status: {status}"
            )
        print("----------------")

    def create_auction(self):
        try:
            description = input("Descrição do leilão: ")
            start_in = int(input("Começa em quantos segundos a partir de agora? "))
            duration = int(input("Duração em segundos: "))
        except ValueError:
            print("Entrada inválida. Use apenas números para tempo.")
            return

        now = int(time.time())
        start_seconds = now + start_in
        end_seconds = start_seconds + duration

        start_ts = Timestamp(seconds=start_seconds)
        end_ts = Timestamp(seconds=end_seconds)

        req = auction_pb2.Auction(
            id=0,  # será definido pelo servidor
            description=description,
            start_time=start_ts,
            end_time=end_ts,
            status="pending",
        )
        created = self.auction_stub.CreateAuction(req)
        print(
            f"Leilão criado: ID={created.id}, Descrição={created.description}, "
            f"Início={created.start_time.seconds}, Fim={created.end_time.seconds}, "
            f"Status={created.status}"
        )


    def place_bid(self):
        try:
            auction_id = int(input("Digite o ID do leilão: "))
            amount = float(input("Digite o valor do lance: "))
        except ValueError:
            print("Entrada inválida. Por favor, digite números.")
            return

        req = bid_pb2.PlaceBidRequest(
            auction_id=auction_id,
            user_id=self.user_id,
            amount=amount,
        )
        resp = self.bid_stub.PlaceBid(req)

        if resp.accepted:
            print(
                f"Lance ACEITO no leilão {resp.auction_id}: {resp.amount:.2f} "
                f"(user {resp.user_id[:8]}...)"
            )
        else:
            print(
                f"Lance RECUSADO no leilão {resp.auction_id}: {resp.amount:.2f}. "
                f"Motivo: {resp.reason}"
            )


def main():
    client = AuctionClient()
    print(f"Cliente iniciado. Seu ID de usuário é: {client.user_id}")

    while True:
        try:
            print("\nOpções:")
            print("1. Listar leilões")
            print("2. Criar leilão")
            print("3. Fazer um lance")
            print("4. Sair")
            choice = input("Escolha uma opção: ")

            if choice == "1":
                client.list_auctions()
            elif choice == "2":
                client.create_auction()
            elif choice == "3":
                client.place_bid()
            elif choice == "4":
                break
            else:
                print("Opção inválida.")
        except KeyboardInterrupt:
            break

    print("Cliente encerrado.")


if __name__ == "__main__":
    main()
