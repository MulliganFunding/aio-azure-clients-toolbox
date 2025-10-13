---- MODULE ConnectionPooling ----
EXTENDS Integers, FiniteSets, Sequences

CONSTANTS
    \* Maximum number of connections in the pool (usually <10)
    MaxPoolSize,
    \* Maximum number of clients per connection (arbitrary, e.g. 10 or 100)
    MaxClientsPerConnection


VARIABLES
    \* Connection states: NONE means no connection exists, CREATING/READY_CHECK are transient states during lock
    connections,     \* connection -> state (NONE, CREATING, READY_CHECK, READY)
    \* Tracks which clients are using which connections
    clientConnections,  \* connection -> set of clients
    \* Locks for connection operations (opening, readiness check, closing)
    openCloseLocks,     \* connection -> locked boolean
    \* Flag indicating connection should be closed when expired
    shouldClose        \* connection -> boolean

vars == <<connections, clientConnections, openCloseLocks, shouldClose>>

\* Connection states - simplified to match implementation
States == {"NONE", "CREATING", "READY_CHECK", "READY"}
\* Set of all possible clients: purposely larger than limit
Clients == 1..(MaxClientsPerConnection + 1)

\* Initial state
Init ==
    /\ connections = [conn \in 1..MaxPoolSize |-> "NONE"]
    /\ clientConnections = [conn \in 1..MaxPoolSize |-> {}]
    /\ openCloseLocks = [conn \in 1..MaxPoolSize |-> FALSE]
    /\ shouldClose = [conn \in 1..MaxPoolSize |-> FALSE]

\* Helper function to check if connection is available (matches implementation's `available` property)
ConnectionAvailable(conn) ==
    /\ connections[conn] = "READY"
    /\ ~openCloseLocks[conn]
    /\ Cardinality(clientConnections[conn]) < MaxClientsPerConnection
    /\ ~shouldClose[conn]  \* Critical: don't allow acquisition if marked to close

\* Helper function to check if connection is closeable (matches implementation's `closeable` property)
ConnectionCloseable(conn) ==
    /\ shouldClose[conn]
    /\ Cardinality(clientConnections[conn]) = 0

\* Actions

\* Client acquires a connection (matches pool's get() and connection's acquire() logic)
AcquireConnection(client) ==
    \E conn \in 1..MaxPoolSize :
        /\ ConnectionAvailable(conn)  \* Use the availability check
        /\ client \notin UNION {clientConnections[c] : c \in 1..MaxPoolSize}
        /\ clientConnections' = [clientConnections EXCEPT ![conn] =
                               clientConnections[conn] \union {client}]
        /\ UNCHANGED <<connections, openCloseLocks, shouldClose>>

\* Client releases a connection (matches checkin logic)
ReleaseConnection(client) ==
    \E conn \in 1..MaxPoolSize :
        /\ client \in clientConnections[conn]
        /\ clientConnections' = [clientConnections EXCEPT ![conn] =
                               clientConnections[conn] \ {client}]
        /\ UNCHANGED <<connections, openCloseLocks, shouldClose>>

\* Mark connection to be closed (matches setting _should_close flag)
MarkConnectionForClosure(conn) ==
    /\ connections[conn] = "READY"
    /\ ~shouldClose[conn]
    /\ shouldClose' = [shouldClose EXCEPT ![conn] = TRUE]
    /\ UNCHANGED <<connections, clientConnections, openCloseLocks>>


\* Create connection (matches create() method with lock)
StartCreating(conn) ==
    /\ connections[conn] = "NONE"
    /\ clientConnections[conn] = {}
    /\ ~openCloseLocks[conn]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = TRUE]
    /\ connections' = [connections EXCEPT ![conn] = "CREATING"]
    /\ UNCHANGED <<clientConnections, shouldClose>>

\* Finish creating connection (unlocks after creation)
FinishCreating(conn) ==
    /\ connections[conn] = "CREATING"
    /\ openCloseLocks[conn]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = FALSE]
    /\ connections' = [connections EXCEPT ![conn] = "READY_CHECK"]
    /\ UNCHANGED <<clientConnections, shouldClose>>

\* Start readiness check (matches check_readiness() method with lock)
StartReadinessCheck(conn) ==
    /\ connections[conn] = "READY_CHECK"
    /\ ~openCloseLocks[conn]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = TRUE]
    /\ UNCHANGED <<connections, clientConnections, shouldClose>>

\* Finish readiness check and mark ready (matches setting _ready event)
FinishReadinessCheck(conn) ==
    /\ connections[conn] = "READY_CHECK"
    /\ openCloseLocks[conn]
    /\ connections' = [connections EXCEPT ![conn] = "READY"]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = FALSE]
    /\ UNCHANGED <<clientConnections, shouldClose>>

\* Start closing a connection (matches close() method with lock, only when closeable)
StartClosing(conn) ==
    /\ ConnectionCloseable(conn)
    /\ ~openCloseLocks[conn]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = TRUE]
    /\ UNCHANGED <<connections, clientConnections, shouldClose>>

\* Finish closing a connection (matches connection reset in close())
FinishClosing(conn) ==
    /\ ConnectionCloseable(conn)
    /\ openCloseLocks[conn]
    /\ connections' = [connections EXCEPT ![conn] = "NONE"]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = FALSE]
    /\ shouldClose' = [shouldClose EXCEPT ![conn] = FALSE]  \* Reset should_close flag
    /\ UNCHANGED clientConnections

\* Next state
Next ==
    \/ \E conn \in 1..MaxPoolSize :
        \/ StartCreating(conn)
        \/ FinishCreating(conn)
        \/ StartReadinessCheck(conn)
        \/ FinishReadinessCheck(conn)
        \/ StartClosing(conn)
        \/ FinishClosing(conn)
        \/ MarkConnectionForClosure(conn)
    \/ \E client \in Clients :
        \/ AcquireConnection(client)
        \/ ReleaseConnection(client)

\* Fairness conditions
Fairness ==
    /\ \A conn \in 1..MaxPoolSize :
        /\ WF_vars(StartCreating(conn) \/ FinishCreating(conn))
        /\ WF_vars(StartReadinessCheck(conn) \/ FinishReadinessCheck(conn))
        /\ WF_vars(StartClosing(conn) \/ FinishClosing(conn))
        /\ WF_vars(MarkConnectionForClosure(conn))
    /\ \A client \in Clients :
        /\ WF_vars(AcquireConnection(client) \/ ReleaseConnection(client))


\* Complete spec
Spec == Init /\ [][Next]_vars /\ Fairness

\* Type invariant
TypeInvariant ==
    /\ connections \in [1..MaxPoolSize -> States]
    /\ clientConnections \in [1..MaxPoolSize -> SUBSET Clients]
    /\ openCloseLocks \in [1..MaxPoolSize -> BOOLEAN]
    /\ shouldClose \in [1..MaxPoolSize -> BOOLEAN]

\* Safety properties (matches implementation guarantees)
SafetyInvariant ==
    \* Clients can only use READY connections that are not marked for closure
    \A conn \in 1..MaxPoolSize :
        Cardinality(clientConnections[conn]) > 0 => connections[conn] = "READY"

\* Additional invariants to check
NoUseDuringTransition ==
    \* No clients can use connections during state transitions or when not ready
    \A conn \in 1..MaxPoolSize :
        (connections[conn] \in {"NONE", "CREATING", "READY_CHECK"}) =>
            clientConnections[conn] = {}

ClientsCannotUseDuringLocks ==
    \* Operations that require locks are mutually exclusive with client usage
    \A conn \in 1..MaxPoolSize :
        openCloseLocks[conn] => clientConnections[conn] = {}

\* Connections marked for closure cannot accept new clients (but existing clients can continue)
\* This is enforced by the ConnectionAvailable check in AcquireConnection
NoNewClientsOnMarkedConnections ==
    \A conn \in 1..MaxPoolSize :
        shouldClose[conn] =>
            \* Marked connections are not available for new acquisitions
            ~ConnectionAvailable(conn)

\* Should close flag consistency
ShouldCloseConsistency ==
    \A conn \in 1..MaxPoolSize :
        shouldClose[conn] => connections[conn] \in {"READY", "NONE"}


\* Helper predicates for temporal properties
ClientCanAcquire(client) ==
    \E conn \in 1..MaxPoolSize :
        /\ ConnectionAvailable(conn)  \* Use the updated availability check
        /\ client \notin UNION {clientConnections[c] : c \in 1..MaxPoolSize}

ClientHasConnection(client) ==
    \E conn \in 1..MaxPoolSize : client \in clientConnections[conn]

AnyConnectionAvailable ==
    \E conn \in 1..MaxPoolSize : ConnectionAvailable(conn)


\* Temporal Properties

\* If a client can acquire a connection, it eventually will
ClientEventuallyAcquires ==
    \A client \in Clients :
        ClientCanAcquire(client) ~> ClientHasConnection(client)

\* Closeable connections eventually get closed
CloseableConnectionsClose ==
    \A conn \in 1..MaxPoolSize :
        ConnectionCloseable(conn) ~> (connections[conn] = "NONE")

\* The pool always eventually has an available connection if needed
PoolEventuallyAvailable ==
    []<>AnyConnectionAvailable

====