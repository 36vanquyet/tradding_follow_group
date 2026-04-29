# GroupTrade Architecture

## Overview

The system listens to Telegram source chats, normalizes incoming messages, stores message state in JSON, keeps trade execution history in SQLite, and exposes a localhost dashboard.

## Block Diagram

```mermaid
flowchart LR
    TG[Telegram Channels / Groups] --> TL[Telethon Listener]
    TL --> MN[Message Normalizer]
    MN --> MS[JSON Message Store]
    MN --> PM[Order Manager]
    PM --> DB[(SQLite Database)]
    PM --> BY[Bybit API]
    PM --> NT[Telegram Notifier]
    DB --> WD[FastAPI Dashboard]
    MS --> WD
```

## Structure Diagram

```mermaid
flowchart TB
    MAIN[app/main.py] --> RT[TelegramRuntime]
    MAIN --> OM[OrderManager]
    MAIN --> MS[TelegramMessageStore]
    MAIN --> DB[(SQLite)]

    RT --> OM
    RT --> NT[TelegramNotifier]

    OM --> NP[MessageNormalizer]
    OM --> AI[AIDecisionEngine]
    OM --> BY[BybitService]
    OM --> RP[Repository]
    OM --> NT

    NP --> SP[SignalParser]
    NP --> OPENAI[OpenAI Responses API]
    SP --> NP
```

## Data Flow

```mermaid
flowchart LR
    M[Incoming Telegram Message] --> R[Record received in JSON]
    R --> N[Normalize message]
    N -->|SIGNAL| S[Create trade signal]
    N -->|CLOSE| C[Close symbol position]
    N -->|SKIPPED| K[Store skipped status]
    N -->|ERROR| E[Store error status]
    S --> A[AI decision]
    A -->|Approved| O[Submit Bybit orders]
    A -->|Rejected| X[Stop]
    O --> H[Persist orders and logs in SQLite]
    C --> H
```

## Sequence Diagram

```mermaid
sequenceDiagram
    participant TG as Telegram
    participant RT as TelegramRuntime
    participant MS as TelegramMessageStore
    participant MN as MessageNormalizer
    participant OM as OrderManager
    participant AI as AIDecisionEngine
    participant BY as BybitService
    participant DB as SQLite

    TG->>RT: NewMessage event
    RT->>MS: record_received()
    RT->>OM: process_message(raw_message, record_id)
    OM->>MN: normalize(raw_message)
    alt signal
        MN-->>OM: normalized signal JSON
        OM->>MS: mark_parsed()
        OM->>DB: create signal / logs
        OM->>AI: evaluate(signal)
        AI-->>OM: approve / reject
        alt approved
            OM->>BY: place_signal_orders()
            OM->>DB: store orders / update signal
        end
    else close
        MN-->>OM: close instruction
        OM->>MS: mark_parsed()
        OM->>BY: close_symbol_position()
    else skipped
        MN-->>OM: unknown
        OM->>MS: mark_skipped()
    end
```

## State Machine

### Telegram Message Lifecycle

```mermaid
stateDiagram-v2
    [*] --> RECEIVED
    RECEIVED --> PARSED: OpenAI/regex normalized as trade signal
    RECEIVED --> PARSED: OpenAI/regex normalized as close instruction
    RECEIVED --> SKIPPED: Not actionable / unparsable
    RECEIVED --> ERROR: Normalization or store failure

    PARSED --> [*]
    SKIPPED --> [*]
    ERROR --> [*]
```

### Trade Signal Lifecycle

```mermaid
stateDiagram-v2
    [*] --> RECEIVED
    RECEIVED --> PARSED: Signal parsed
    PARSED --> APPROVED: AI approved
    PARSED --> REJECTED: AI rejected
    APPROVED --> ORDER_SUBMITTED: Bybit orders sent
    APPROVED --> ERROR: Bybit submission failed
    ORDER_SUBMITTED --> CLOSED: PnL sync matched closed trade
    APPROVED --> CANCELLED: Cancel command issued
    ORDER_SUBMITTED --> CANCELLED: Cancel command issued
    RECEIVED --> ERROR: Parse failure or runtime failure
    PARSED --> ERROR: Runtime failure
    REJECTED --> [*]
    CANCELLED --> [*]
    CLOSED --> [*]
    ERROR --> [*]
```

## Data Model

```mermaid
erDiagram
    trade_signals ||--o{ trade_orders : has
    trade_signals ||--o{ execution_logs : has
    trade_signals ||--o{ pnl_records : has

    trade_signals {
        int id
        string source_chat_id
        string source_chat_name
        string raw_message
        string symbol
        string side
        float entry_price
        float stop_loss
        float tp1
        float tp2
        string status
    }

    trade_orders {
        int id
        int signal_id
        string role
        string side
        string order_type
        float qty
        float price
        string status
    }

    execution_logs {
        int id
        int signal_id
        string level
        string message
        string context_json
    }

    pnl_records {
        int id
        int signal_id
        string symbol
        string side
        float qty
        float closed_pnl
        float fees
    }
```

## Runtime Components

| Component | Responsibility |
| --- | --- |
| `TelegramRuntime` | Starts Telethon listener, Telegram bot commands, and sync loop |
| `MessageNormalizer` | Converts raw Telegram text into a normalized JSON-like object |
| `TelegramMessageStore` | Stores receive/parse/skip/error state in JSON |
| `OrderManager` | Controls parsing, AI decision, order submission, and error handling |
| `Repository` | Reads/writes SQLite trade data |
| `BybitService` | Places, cancels, and closes futures orders |
| `AIDecisionEngine` | Filters signals before execution |
