# INC-1010: order status stale at checkout

Root cause: postgres-orders, a slow query on the orders replica.
Path: postgres-orders -> payments-api -> checkout-api.
What the map missed: checkout-api reads the order status directly from the orders database through a shared library, so it depends on postgres-orders without going through payments-api.
