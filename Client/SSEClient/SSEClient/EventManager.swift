//
//  EventManager.swift
//  SSEClient
//
//  Created by Rodrigo Yamauchi on 21/10/25.
//

// CLI Command para testes com o sse do api_gateway:
// curl http://localhost:8000/events  -H 'Accept-Encoding: gzip,deflate,sdch' --compressed

import Foundation
import EventSource
import Combine
import AppKit

// Modelo de Auction existente
struct Auction: Decodable, Identifiable {
    let id: Int
    let description: String
    let start_time: String
    let end_time: String
    let status: String
}

@MainActor
class EventManager: ObservableObject {
    
    // --- Propriedades de Estado ---
    
    @Published var apiMessage: String = ""
    @Published var connectionStatus: String = "Disconnected"
    
    // Payloads de eventos SSE
    @Published var lastError: BidErrorPayload?
    @Published var lastBid: BidUpdatePayload?
    @Published var auctionResult: AuctionEndPayload?
    @Published var paymentInfo: PaymentInfoPayload?
    @Published var paymentStatus: PaymentStatusPayload?
    
    // --- Configuração ---
    let baseURL = "http://localhost:8000"
    
    private var eventSource: EventSource?
    private var sseTask: Task<Void, Error>?

    // --- Gerenciamento de Conexão SSE ---

    func connectSSE(userId: String) {
        guard !userId.isEmpty else {
            self.connectionStatus = "User ID cannot be empty."
            return
        }
        
        disconnectSSE()
        
        guard let sseURL = URL(string: "\(baseURL)/events?channel=user_\(userId)") else {
            self.connectionStatus = "Invalid SSE URL."
            return
        }
        
        print("Connecting to SSE channel: \(sseURL.absoluteString)")
        
        let eventSource = EventSource()
        self.eventSource = eventSource
        
        self.sseTask = Task {
            let dataTask = eventSource.dataTask(for: URLRequest(url: sseURL))
            for await event in dataTask.events() {
                // Atualiza o status no MainActor
                Task { @MainActor in
                    switch event {
                    case .open:
                        self.connectionStatus = "Connection Opened"
                        print("SSE connection was opened.")
                        
                    case .error(let error):
                        self.connectionStatus = "Error: \(error.localizedDescription)"
                        print("SSE received an error:", error.localizedDescription)
                        
                    case .event(let eventMessage):
                        // Manipular evento nomeado
                        self.handleNamedEvent(eventMessage)
                        
                    case .closed:
                        self.connectionStatus = "Connection Closed"
                        print("SSE connection was closed.")
                    }
                }
            }
        }
    }
    
    func disconnectSSE() {
        self.sseTask?.cancel()
        self.eventSource = nil
        self.connectionStatus = "Disconnected"
        print("SSE disconnected")
    }
    
    private func handleNamedEvent(_ event: EVEvent) {
        guard let eventName = event.event, let eventDataString = event.data else {
            print("Received generic event (or keepalive)")
            return
        }
        
        print("🔔 Received named event: '\(eventName)', data: \(eventDataString)")
        
        let decoder = JSONDecoder()
        
        guard let data = eventDataString.data(using: String.Encoding.utf8) else {
            print("Failed to get data from event string")
            return
        }
        
        do {
            // Decodifica com base no eventName
            switch eventName {
                
            case "bid_update":
                // 1. Decodifica a wrapper
                let wrapper = try decoder.decode(EventWrapper<BidUpdatePayload>.self, from: data)
                // 2. Extrai o payload interno
                self.lastBid = wrapper.payload
                self.apiMessage = "New bid: \(self.lastBid?.amount ?? 0) by \(self.lastBid?.user_id ?? "unknown")"
                
            case "bid_error":
                let wrapper = try decoder.decode(EventWrapper<BidErrorPayload>.self, from: data)
                self.lastError = wrapper.payload
                // Agora "reason" pode ser nil
                self.apiMessage = "Bid Error: \(self.lastError?.reason ?? "Invalid bid")"
                
            case "auction_end":
                let wrapper = try decoder.decode(EventWrapper<AuctionEndPayload>.self, from: data)
                self.auctionResult = wrapper.payload
                if self.auctionResult?.is_winner == true {
                    self.apiMessage = "Congrats! You won auction \(String(self.auctionResult!.auction_id) ?? "")!"
                } else {
                    self.apiMessage = "Auction \(String(self.auctionResult!.auction_id) ?? "") ended. Winner: \(self.auctionResult?.winner_id ?? "N/A")"
                }
                
            case "payment_info":
                let wrapper = try decoder.decode(EventWrapper<PaymentInfoPayload>.self, from: data)
                self.paymentInfo = wrapper.payload
                self.apiMessage = "Payment link received for auction \(String(self.paymentInfo!.auction_id) ?? "")"
                if let urlString = self.paymentInfo?.payment_link, let url = URL(string: urlString) {
                    NSWorkspace.shared.open(url)
                    print("Payment URL: \(url.absoluteString)")
                }
                
            case "payment_status":
                let wrapper = try decoder.decode(EventWrapper<PaymentStatusPayload>.self, from: data)
                self.paymentStatus = wrapper.payload
                if self.paymentStatus?.status == "approved" {
                    self.apiMessage = "Payment Approved!"
                } else {
                    self.apiMessage = "Payment Error: \(self.paymentStatus?.reason ?? "Failed")"
                }
                
            case "keepalive":
                print("💓 Connection alive")
                self.connectionStatus = "Connected (Online)"
                
            default:
                print("Received unhandled event type: \(eventName)")
            }
        } catch {
            // Este log agora será muito mais informativo sobre o *real* erro
            print("Failed to decode JSON for event '\(eventName)': \(error)")
            self.apiMessage = "Failed to parse event: \(eventName)"
        }
    }


    // --- Funções da API REST (Modernizadas com async/await) ---
    
    private func performRequest<T: Codable>(url: URL, method: String, payload: T?) async throws -> String {
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        if let payload = payload {
            req.httpBody = try? JSONEncoder().encode(payload)
        }

        let (data, response) = try await URLSession.shared.data(for: req)
        
        guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
            let errorResult = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw NSError(domain: "APIError", code: (response as? HTTPURLResponse)?.statusCode ?? 500, userInfo: [NSLocalizedDescriptionKey: errorResult])
        }
        
        return String(data: data, encoding: .utf8) ?? "Success (no data)"
    }
    
    // --- Modelos para API REST ---
    struct InterestPayload: Codable {
        let user_id: String
        let auction_id: String
    }
    
    struct BidPayload: Codable {
        let user_id: String
        let auction_id: String
        let amount: Double
    }
    
    struct CreateAuctionPayload: Codable {
        let description: String
        let start_time: String // ISO
        let end_time: String   // ISO
    }

    // REST API: Register Interest
    func registerInterest(userId: String, auctionId: String) async {
        guard !userId.isEmpty, !auctionId.isEmpty else { return }
        guard let url = URL(string: "\(baseURL)/api/interest") else { return }
        let payload = InterestPayload(user_id: userId, auction_id: auctionId)
        
        do {
            let result = try await performRequest(url: url, method: "POST", payload: payload)
            self.apiMessage = "Register: \(result)"
        } catch {
            self.apiMessage = "Register Error: \(error.localizedDescription)"
        }
    }

    // REST API: Cancel Interest
    func cancelInterest(userId: String, auctionId: String) async {
        guard !userId.isEmpty, !auctionId.isEmpty else { return }
        guard let url = URL(string: "\(baseURL)/api/interest") else { return }
        let payload = InterestPayload(user_id: userId, auction_id: auctionId)
        
        do {
            let result = try await performRequest(url: url, method: "DELETE", payload: payload)
            self.apiMessage = "Cancel: \(result)"
        } catch {
            self.apiMessage = "Cancel Error: \(error.localizedDescription)"
        }
    }
    
    // REST API: Place Bid
    func placeBid(userId: String, auctionId: String, amount: String) async {
        guard !userId.isEmpty, !auctionId.isEmpty, !amount.isEmpty else { return }
        guard let url = URL(string: "\(baseURL)/api/bid") else { return }
        let payload = BidPayload(user_id: userId, auction_id: auctionId, amount: Double(amount) ?? 0.0)
        
        do {
            let result = try await performRequest(url: url, method: "POST", payload: payload)
            self.apiMessage = "Bid: \(result)"
        } catch {
            self.apiMessage = "Bid Error: \(error.localizedDescription)"
        }
    }
    
    // REST API: Create Auction
    func createAuction(description: String, startTime: String, endTime: String) async -> String {
        guard !description.isEmpty, !startTime.isEmpty, !endTime.isEmpty else { return "Invalid inputs" }
        guard let url = URL(string: "\(baseURL)/api/auction") else { return "Invalid URL" }
        let payload = CreateAuctionPayload(description: description, start_time: startTime, end_time: endTime)
        
        do {
            return try await performRequest(url: url, method: "POST", payload: payload)
        } catch {
            return "Create Error: \(error.localizedDescription)"
        }
    }
    
    // REST API: Fetch Auctions
    func fetchAuctions() async -> [Auction] {
        guard let url = URL(string: "\(baseURL)/api/auction") else { return [] }
        
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let auctions = (try? JSONDecoder().decode([Auction].self, from: data)) ?? []
            return auctions
        } catch {
            print("Error fetching auctions: \(error)")
            self.apiMessage = "Failed to fetch auctions."
            return []
        }
    }
}
