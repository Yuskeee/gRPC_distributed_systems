//
//  EventPayloads.swift
//  SSEClient
//
//  Created by Rodrigo Yamauchi on 10/11/25.
//

import Foundation

struct EventWrapper<T: Codable>: Codable {
    let event_type: String
    let payload: T
    let timestamp: String
}

struct BidUpdatePayload: Codable, Hashable {
    let auction_id: Int
    let user_id: String
    let amount: Double
}

struct BidErrorPayload: Codable, Hashable {
    let auction_id: Int
    let user_id: String
    let amount: Double
    let reason: String?
}

struct AuctionEndPayload: Codable, Hashable {
    let auction_id: Int
    let winner_id: String?
    let winning_amount: Double?
    let is_winner: Bool
}

struct PaymentInfoPayload: Codable, Hashable {
    let auction_id: Int
    let customer_id: String
    let payment_link: String
    let status: String
    let transaction_id: String
    let timestamp: String?
}

struct PaymentStatusPayload: Codable, Hashable {
    let auction_id: Int
    let status: String
    let reason: String?
}
