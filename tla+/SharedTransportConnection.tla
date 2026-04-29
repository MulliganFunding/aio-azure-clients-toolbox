---------------------------- MODULE SharedTransportConnection ----------------------------
\* Spec for: SharedTransportConnection lifecycle in connection_pooling.py
\* Models the state machine of a single SharedTransportConnection slot,
\* focusing on the Closed -> Opening -> Ready -> Closed lifecycle and the
\* interactions between concurrent clients, timeouts, and cancellation.
\*
\* Client tracking: we distinguish two populations —
\*   waiting_count — clients inside CapacityLimiter but blocked on _ready.wait()
\*   active_count  — clients that have passed _ready.wait() and are using the conn
\* The implementation's client_limiter.borrowed_tokens = waiting_count + active_count.
\* The "opener" (the client running check_readiness) is counted in waiting_count
\* until readiness succeeds, at which point all waiters become active.
\*
\* Key actions:
\*   Checkout          — a client creates a connection and begins readiness check
\*   ReadySuccess      — check_readiness() succeeds; all waiters become active
\*   ReadyFail         — check_readiness() fails (ready() returns False); inline
\*                        cleanup resets to Closed, waiters will time out
\*   CheckoutCancelled — move_on_after cancels checkout mid-readiness-check;
\*                        try/except BaseException handler cleans up (lines 311-324)
\*   StuckDetected     — ConnectionPool.get() detects Opening slot with no clients
\*                        and closes it (lines 544-553, defense-in-depth)
\*   WaiterJoin        — a new client joins while Opening, blocked on _ready.wait()
\*   WaiterTimeout     — a waiting client times out (move_on_after in acquire())
\*   Checkin           — an active client releases the connection
\*   Expire            — idle/lifespan timeout triggers should_close
\*   Close             — explicit close when no active clients
\*
\* Safety invariants:
\*   TypeOK             — all variables in expected domains
\*   NoReadyWithoutConn — ready_event implies conn_state is not Closed
\*   NoActiveOnClosed   — active_count > 0 implies conn_state = Ready
\*
\* Liveness property:
\*   NeverStuckPermanently — Opening with ready_event=FALSE and total clients=0
\*                           is eventually resolved
\*
\* Corresponds to: aio_azure_clients_toolbox/connection_pooling.py
\* Verified: 2026-04-28 with TLC (MaxClients=3, 0 errors)

EXTENDS Naturals, FiniteSets

CONSTANTS
    MaxClients   \* max concurrent clients (small for model checking)

VARIABLES
    conn_state,      \* "Closed" | "Opening" | "Ready"
    ready_event,     \* TRUE | FALSE (models anyio.Event _ready)
    waiting_count,   \* clients inside limiter, blocked on _ready.wait()
    active_count,    \* clients past _ready.wait(), actively using conn
    should_close     \* TRUE | FALSE (models _should_close flag)

vars == <<conn_state, ready_event, waiting_count, active_count, should_close>>

total_clients == waiting_count + active_count

TypeOK ==
    /\ conn_state \in {"Closed", "Opening", "Ready"}
    /\ ready_event \in {TRUE, FALSE}
    /\ waiting_count \in 0..MaxClients
    /\ active_count \in 0..MaxClients
    /\ total_clients \in 0..MaxClients
    /\ should_close \in {TRUE, FALSE}

\* Safety: if ready_event is set, connection must exist
NoReadyWithoutConn ==
    ready_event = TRUE => conn_state /= "Closed"

\* Safety: active clients only exist on Ready connections
NoActiveOnClosed ==
    active_count > 0 => conn_state = "Ready"

\* Safety: waiting clients cannot exist on Ready connections
\* (ReadySuccess converts all waiters to active). Waiters CAN exist
\* transiently in Closed state — these are orphaned waiters on a stale
\* _ready Event that will time out via WaiterTimeout.
NoWaitersOnReady ==
    conn_state = "Ready" => waiting_count = 0

\* ---- Initial state ----

Init ==
    /\ conn_state = "Closed"
    /\ ready_event = FALSE
    /\ waiting_count = 0
    /\ active_count = 0
    /\ should_close = FALSE

\* ---- Actions ----

\* A client arrives at a Closed slot, calls checkout() which calls create()
\* then begins check_readiness(). The client enters CapacityLimiter (waiting).
\* Models lines ~304-312 of checkout().
Checkout ==
    /\ conn_state = "Closed"
    /\ total_clients < MaxClients
    /\ conn_state' = "Opening"
    /\ waiting_count' = waiting_count + 1
    /\ UNCHANGED <<ready_event, active_count, should_close>>

\* check_readiness() succeeds: _ready event is set, state becomes Ready.
\* All waiting clients (including the opener) pass _ready.wait() and
\* become active.
\* Models lines ~407-409 of check_readiness().
ReadySuccess ==
    /\ conn_state = "Opening"
    /\ ready_event = FALSE
    /\ waiting_count > 0
    /\ conn_state' = "Ready"
    /\ ready_event' = TRUE
    /\ active_count' = active_count + waiting_count
    /\ waiting_count' = 0
    /\ UNCHANGED <<should_close>>

\* check_readiness() fails (ready() returns False). The opener performs
\* inline cleanup: closes connection, resets _connection=None, replaces
\* _ready with new Event, raises ConnectionFailed. The opener's
\* CapacityLimiter token is released. Other waiters are now waiting on
\* an orphaned Event that will never fire; they'll time out separately.
\* Models lines ~410-424 of check_readiness().
ReadyFail ==
    /\ conn_state = "Opening"
    /\ ready_event = FALSE
    /\ waiting_count > 0
    /\ conn_state' = "Closed"
    /\ ready_event' = FALSE
    /\ waiting_count' = waiting_count - 1    \* opener leaves
    /\ should_close' = FALSE
    /\ UNCHANGED <<active_count>>

\* move_on_after cancels checkout() while check_readiness() is running.
\* The try/except BaseException handler detects _connection is not None
\* and _ready is not set, closes the connection, resets state.
\* The cancelled client's CapacityLimiter token is released.
\* Other waiters are on an orphaned Event; they'll time out separately.
\* Models lines ~311-324 of checkout().
CheckoutCancelled ==
    /\ conn_state = "Opening"
    /\ ready_event = FALSE
    /\ waiting_count > 0
    /\ conn_state' = "Closed"
    /\ ready_event' = FALSE
    /\ waiting_count' = waiting_count - 1
    /\ should_close' = FALSE
    /\ UNCHANGED <<active_count>>

\* A waiting client on an orphaned _ready Event times out via move_on_after
\* in acquire(). Its CapacityLimiter token is released. This happens when
\* the connection was reset (ReadyFail or CheckoutCancelled) while the
\* client was blocked on the old Event. The connection is already Closed,
\* so no state change other than decrementing the orphaned waiter.
\* In our model, after ReadyFail/CheckoutCancelled sets conn_state=Closed,
\* remaining waiters drain via this action.
WaiterTimeout ==
    /\ conn_state = "Closed"
    /\ waiting_count > 0
    /\ waiting_count' = waiting_count - 1
    /\ UNCHANGED <<conn_state, ready_event, active_count, should_close>>

\* A new client joins while Opening; it enters CapacityLimiter and blocks
\* on _ready.wait(). Models the path in checkout() at line ~330 where
\* _connection is already set, so it skips create() and waits.
WaiterJoin ==
    /\ conn_state = "Opening"
    /\ total_clients < MaxClients
    /\ waiting_count' = waiting_count + 1
    /\ UNCHANGED <<conn_state, ready_event, active_count, should_close>>

\* A new client joins when Ready: _ready.wait() returns immediately,
\* so the client goes straight to active.
CheckoutReady ==
    /\ conn_state = "Ready"
    /\ total_clients < MaxClients
    /\ active_count' = active_count + 1
    /\ UNCHANGED <<conn_state, ready_event, waiting_count, should_close>>

\* ConnectionPool.get() stuck-connection detector: finds a slot where
\* _connection is not None (Opening), _ready is not set, and
\* current_client_count == 0. Calls close() to reset the slot.
\* Models lines ~544-553 of ConnectionPool.get().
StuckDetected ==
    /\ conn_state = "Opening"
    /\ ready_event = FALSE
    /\ waiting_count = 0
    /\ active_count = 0
    /\ conn_state' = "Closed"
    /\ ready_event' = FALSE
    /\ should_close' = FALSE
    /\ UNCHANGED <<waiting_count, active_count>>

\* An active client finishes and checks in.
\* Models checkin() (lines ~339-352).
Checkin ==
    /\ active_count > 0
    /\ conn_state = "Ready"
    /\ active_count' = active_count - 1
    /\ UNCHANGED <<conn_state, ready_event, waiting_count, should_close>>

\* Connection expires (idle timeout or lifespan exceeded). Sets should_close.
\* Models the expiration check in checkout() lines ~297-302 and
\* checkin() lines ~348-350.
Expire ==
    /\ conn_state = "Ready"
    /\ should_close = FALSE
    /\ should_close' = TRUE
    /\ UNCHANGED <<conn_state, ready_event, waiting_count, active_count>>

\* Connection is closed (explicit close, expired close, or pool cleanup).
\* Only fires when no active clients are using it.
\* Models close() (lines ~436-454).
Close ==
    /\ conn_state = "Ready"
    /\ active_count = 0
    /\ conn_state' = "Closed"
    /\ ready_event' = FALSE
    /\ should_close' = FALSE
    /\ UNCHANGED <<waiting_count, active_count>>

\* ---- Specification ----

Next ==
    \/ Checkout
    \/ ReadySuccess
    \/ ReadyFail
    \/ CheckoutCancelled
    \/ WaiterTimeout
    \/ WaiterJoin
    \/ CheckoutReady
    \/ StuckDetected
    \/ Checkin
    \/ Expire
    \/ Close

\* Fairness: cleanup and timeout actions are weakly fair so stuck states resolve.
Fairness ==
    /\ WF_vars(ReadySuccess)
    /\ WF_vars(ReadyFail)
    /\ WF_vars(CheckoutCancelled)
    /\ WF_vars(StuckDetected)
    /\ WF_vars(WaiterTimeout)
    /\ WF_vars(Close)

Spec == Init /\ [][Next]_vars /\ Fairness

\* ---- Liveness ----

\* A connection that is Opening with ready_event=FALSE and no clients at all
\* (the "stuck" state from the implementation's perspective) will eventually
\* be cleaned up.
NeverStuckPermanently ==
    (conn_state = "Opening" /\ ready_event = FALSE /\ total_clients = 0)
        ~> (conn_state /= "Opening" \/ ready_event = TRUE \/ total_clients > 0)

=============================================================================
