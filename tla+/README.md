# TLA+ Specs

This directory contains specs for TLA+ to validate using the TLC model-checker.

TLA+ is a language for writing specs for asynchronous algorithms. Specs have been provided in order to validate our behavior satisfies expectations.

To run these, please download the TLC model checker and after loading the module, create a new model with a "behavior spec" of `Temporal formula` pointing to the `Spec` operator.

With in the "behavior spec" section, set the value of the constants to the following:

- `MaxPoolSize <- 3`
- `MaxClientsPerConnection <- 5`

Under "What to check?", consider the following safety properties:

![](./properties-screenshot.png)

## State Graph

The state-graph here is a pdf output by tla2tools.jar:

```sh
java -cp /Applications/TLA+\ Toolbox.app/Contents/Eclipse/tla2tools.jar tlc2.TLC -dump dot graph.dot ./SharedTransportConnection.tla
dot -Tpdf graph.dot -o state-graph.pdf
```

I have also asked a coding agent to render it as a mermaid diagram below:

```mermaid
stateDiagram-v2
    state "Closed\nactive=0 waiting=0\nshould_close=F ready=F" as S1
    state "Opening\nactive=0 waiting=1\nshould_close=F ready=F" as S2
    state "Ready\nactive=1 waiting=0\nshould_close=F ready=T" as S3
    state "Opening\nactive=0 waiting=2\nshould_close=F ready=F" as S4
    state "Ready\nactive=2 waiting=0\nshould_close=F ready=T" as S5
    state "Ready\nactive=0 waiting=0\nshould_close=F ready=T" as S6
    state "Ready\nactive=1 waiting=0\nshould_close=T ready=T" as S7
    state "Closed\nactive=0 waiting=1\nshould_close=F ready=F" as S8
    state "Opening\nactive=0 waiting=3\nshould_close=F ready=F" as S9
    state "Ready\nactive=3 waiting=0\nshould_close=F ready=T" as S10
    state "Ready\nactive=2 waiting=0\nshould_close=T ready=T" as S11
    state "Ready\nactive=0 waiting=0\nshould_close=T ready=T" as S12
    state "Closed\nactive=0 waiting=2\nshould_close=F ready=F" as S13
    state "Ready\nactive=3 waiting=0\nshould_close=T ready=T" as S14

    [*] --> S1

    %% Checkout (Closed → Opening, waiting+1)
    S1 --> S2 : Checkout
    S8 --> S4 : Checkout
    S13 --> S9 : Checkout

    %% ReadySuccess (Opening → Ready, all waiters become active)
    S2 --> S3 : ReadySuccess
    S4 --> S5 : ReadySuccess
    S9 --> S10 : ReadySuccess

    %% ReadyFail / CheckoutCancelled (Opening → Closed, waiting-1)
    S2 --> S1 : ReadyFail / Cancelled
    S4 --> S8 : ReadyFail / Cancelled
    S9 --> S13 : ReadyFail / Cancelled

    %% WaiterJoin (Opening, waiting+1)
    S2 --> S4 : WaiterJoin
    S4 --> S9 : WaiterJoin

    %% WaiterTimeout (Closed, waiting-1)
    S8 --> S1 : WaiterTimeout
    S13 --> S8 : WaiterTimeout

    %% CheckoutReady (Ready, active+1)
    S6 --> S3 : CheckoutReady
    S3 --> S5 : CheckoutReady
    S5 --> S10 : CheckoutReady
    S12 --> S7 : CheckoutReady
    S7 --> S11 : CheckoutReady
    S11 --> S14 : CheckoutReady

    %% Checkin (Ready, active-1)
    S3 --> S6 : Checkin
    S5 --> S3 : Checkin
    S10 --> S5 : Checkin
    S7 --> S12 : Checkin
    S11 --> S7 : Checkin
    S14 --> S11 : Checkin

    %% Expire (should_close: F → T)
    S3 --> S7 : Expire
    S5 --> S11 : Expire
    S6 --> S12 : Expire
    S10 --> S14 : Expire

    %% Close (Ready, active=0 → Closed)
    S6 --> S1 : Close
    S12 --> S1 : Close
```
