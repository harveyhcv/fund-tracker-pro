//
//  Item.swift
//  Fund Tracker Pro
//
//  Created by Harvey Nguyen on 1/4/26.
//

import Foundation
import SwiftData

@Model
final class Item {
    var timestamp: Date
    
    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
