---- MODULE ConnectionPooling ----
EXTENDS Integers, FiniteSets, Sequences

CONSTANTS
    \* Maximum number of connections in the pool (usually <10)
    MaxPoolSize,
    \* Maximum number of clients per connection (arbitrary, e.g. 10 or 100)
    MaxClientsPerConnection


VARIABLES
    \* Connection states: None means no connection exists
    connections,     \* connection -> state (NONE, OPENING, READY, CLOSING)
    \* Tracks which clients are using which connections
    clientConnections,  \* connection -> set of clients
    \* Locks for connection operations
    openCloseLocks     \* connection -> locked boolean

vars == <<connections, clientConnections, openCloseLocks>>

\* Connection states
States == {"NONE", "OPENING", "READY", "CLOSING"}
\* Set of all possible clients: purposely larger than limit
Clients == 1..(MaxClientsPerConnection + 1)

\* Initial state
Init ==
    /\ connections = [conn \in 1..MaxPoolSize |-> "NONE"]
    /\ clientConnections = [conn \in 1..MaxPoolSize |-> {}]
    /\ openCloseLocks = [conn \in 1..MaxPoolSize |-> FALSE]

\* Helper function to find available connection
GetAvailableConnection(client) ==
    CHOOSE conn \in 1..MaxPoolSize :
        /\ connections[conn] = "READY"
        /\ ~openCloseLocks[conn]
        /\ Cardinality(clientConnections[conn]) < MaxClientsPerConnection
        /\ client \notin clientConnections[conn]

\* Actions

\* Client acquires a connection
AcquireConnection(client) ==
    \E conn \in 1..MaxPoolSize :
        /\ connections[conn] = "READY"
        /\ ~openCloseLocks[conn]
        /\ Cardinality(clientConnections[conn]) < MaxClientsPerConnection
        /\ client \notin UNION {clientConnections[c] : c \in 1..MaxPoolSize}
        /\ clientConnections' = [clientConnections EXCEPT ![conn] =
                               clientConnections[conn] \union {client}]
        /\ UNCHANGED <<connections, openCloseLocks>>

\* Client releases a connection
ReleaseConnection(client) ==
    \E conn \in 1..MaxPoolSize :
        /\ client \in clientConnections[conn]
        /\ clientConnections' = [clientConnections EXCEPT ![conn] =
                               clientConnections[conn] \ {client}]
        /\ UNCHANGED <<connections, openCloseLocks>>


\* Start opening a connection
StartOpening(conn) ==
    /\ connections[conn] \in {"NONE", "CLOSING"}
    /\ clientConnections[conn] = {}
    /\ ~openCloseLocks[conn]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = TRUE]
    /\ connections' = [connections EXCEPT ![conn] = "OPENING"]
    /\ UNCHANGED clientConnections

\* Finish opening a connection
FinishOpening(conn) ==
    /\ connections[conn] = "OPENING"
    /\ clientConnections[conn] = {}
    /\ openCloseLocks[conn]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = FALSE]
    /\ UNCHANGED <<clientConnections, connections>>

\* Start establish ready
StartEstablishReady(conn) ==
    /\ connections[conn] = "OPENING"
    /\ clientConnections[conn] = {}
    /\ ~openCloseLocks[conn]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = TRUE]
    /\ connections' = [connections EXCEPT ![conn] = "READY"]
    /\ UNCHANGED clientConnections

\* Finish establish ready
FinishEstablishReady(conn) ==
    /\ connections[conn] = "READY"
    /\ openCloseLocks[conn]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = FALSE]
    /\ UNCHANGED <<clientConnections, connections>>


\* Start closing a connection
StartClosing(conn) ==
    /\ connections[conn] = "READY"
    /\ clientConnections[conn] = {}
    /\ ~openCloseLocks[conn]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = TRUE]
    /\ connections' = [connections EXCEPT ![conn] = "CLOSING"]
    /\ UNCHANGED clientConnections

\* Finish closing a connection
FinishClosing(conn) ==
    /\ connections[conn] = "CLOSING"
    /\ clientConnections[conn] = {}
    /\ openCloseLocks[conn]
    /\ connections' = [connections EXCEPT ![conn] = "NONE"]
    /\ openCloseLocks' = [openCloseLocks EXCEPT ![conn] = FALSE]
    /\ UNCHANGED clientConnections

\* Next state
Next ==
    \/ \E conn \in 1..MaxPoolSize :
        \/ StartOpening(conn)
        \/ FinishOpening(conn)
        \/ StartEstablishReady(conn)
        \/ FinishEstablishReady(conn)
        \/ StartClosing(conn)
        \/ FinishClosing(conn)
    \/ \E client \in Clients :
        \/ AcquireConnection(client)
        \/ ReleaseConnection(client)

\* Fairness conditions
Fairness ==
    /\ \A conn \in 1..MaxPoolSize :
        /\ WF_vars(StartOpening(conn) \/ FinishOpening(conn))
        /\ WF_vars(StartEstablishReady(conn) \/ FinishEstablishReady(conn))
        /\ WF_vars(StartClosing(conn) \/ FinishClosing(conn))
    /\ \A client \in Clients :
        /\ WF_vars(AcquireConnection(client) \/ ReleaseConnection(client))


\* Complete spec
Spec == Init /\ [][Next]_vars /\ Fairness

\* Type invariant
TypeInvariant ==
    /\ connections \in [1..MaxPoolSize -> States]
    /\ clientConnections \in [1..MaxPoolSize -> SUBSET Clients]
    /\ openCloseLocks \in [1..MaxPoolSize -> BOOLEAN]

\* Safety properties
SafetyInvariant ==
    \* Clients can only use READY connections
    \A conn \in 1..MaxPoolSize :
        Cardinality(clientConnections[conn]) > 0 => connections[conn] = "READY"

\* Additional invariants to check
NoUseDuringTransition ==
    \* No clients can use connections during state transitions
    \A conn \in 1..MaxPoolSize :
        (connections[conn] \in {"OPENING", "CLOSING", "NONE"}) =>
            clientConnections[conn] = {}

ClientsCannotUseDuringLocks ==
    \* Operations that require locks are mutually exclusive
    \A conn \in 1..MaxPoolSize :
        openCloseLocks[conn] =>
            connections[conn] \in {"OPENING", "CLOSING", "READY"}
            /\ clientConnections[conn] = {}


\* Helper predicates for temporal properties
ClientCanAcquire(client) ==
    \E conn \in 1..MaxPoolSize :
        /\ connections[conn] = "READY"
        /\ ~openCloseLocks[conn]
        /\ Cardinality(clientConnections[conn]) < MaxClientsPerConnection
        /\ client \notin UNION {clientConnections[c] : c \in 1..MaxPoolSize}

ClientHasConnection(client) ==
    \E conn \in 1..MaxPoolSize : client \in clientConnections[conn]

ConnectionAvailable ==
    \E conn \in 1..MaxPoolSize :
        /\ connections[conn] = "READY"
        /\ ~openCloseLocks[conn]
        /\ Cardinality(clientConnections[conn]) < MaxClientsPerConnection


\* Temporal Properties

\* If a client can acquire a connection, it eventually will
ClientEventuallyAcquires ==
    \A client \in Clients :
        ClientCanAcquire(client) ~> ClientHasConnection(client)

\* Connections that start opening eventually become ready
ConnectionEventuallyReady ==
    \A conn \in 1..MaxPoolSize :
        (connections[conn] = "OPENING") ~> (connections[conn] = "READY")

\* Connections that start closing eventually finish closing
ConnectionEventuallyCloses ==
    \A conn \in 1..MaxPoolSize :
        (connections[conn] = "CLOSING") ~> (connections[conn] = "NONE")

\* If no clients are using a connection, it can eventually be closed and recycled
ConnectionEventuallyRecyclable ==
    \A conn \in 1..MaxPoolSize :
        (\/ connections[conn] = "READY"
         /\ clientConnections[conn] = {}) ~>
        (connections[conn] = "NONE")

\* The pool always eventually has an available connection if needed
PoolEventuallyAvailable ==
    []<>ConnectionAvailable

\* No client holds a connection forever
NoEternalHold ==
    \A client \in Clients :
        [](ClientHasConnection(client) ~> ~ClientHasConnection(client))

====