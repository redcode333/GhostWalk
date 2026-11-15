"""Sample `acme` repos for the onboarding demo (no GitHub App needed). Real files, parsed by the real parsers."""

CHECKOUT_COMPOSE = """\
services:
  checkout-api:
    image: acme/checkout-api
    depends_on: [payments, cart, inventory]
    environment:
      CONFIG_SVC_URL: http://config-svc:8080
      PRICING_URL: http://pricing:8080
  cart:
    image: acme/cart
    depends_on: [redis-main]
    environment:
      REDIS_URL: redis://redis-main:6379/0
  inventory:
    image: acme/inventory
    depends_on: [postgres-inv]
    environment:
      DATABASE_URL: postgres://postgres-inv:5432/inventory
  pricing:
    image: acme/pricing
    depends_on: [config-svc]
  payments:
    image: acme/payments
  postgres-inv:
    image: postgres:16
  redis-main:
    image: redis:7
  config-svc:
    image: acme/config-svc
"""

PAYMENTS_COMPOSE = """\
services:
  payments:
    image: acme/payments
    depends_on:
      postgres-pay: {condition: service_healthy}
      fraud-check: {condition: service_started}
    environment:
      - DATABASE_URL=postgres://postgres-pay:5432/pay
      - NOTIFY_URL=http://notifications:8080
      - STRIPE_URL=https://api.stripe.com/v1
  fraud-check:
    image: acme/fraud-check
    environment:
      - CONFIG_SVC_URL=http://config-svc:8080
  notifications:
    image: acme/notifications
    depends_on: [kafka-main]
  postgres-pay:
    image: postgres:16
  kafka-main:
    image: bitnami/kafka
  config-svc:
    image: acme/config-svc
"""

PAYMENTS_ENV = "SEARCH_URL=http://search:9200\nLOG_LEVEL=info\n"

INFRA_K8S = """\
apiVersion: v1
kind: Service
metadata: {name: checkout-api}
---
apiVersion: v1
kind: Service
metadata: {name: search}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: {name: web-edge}
spec:
  rules:
    - host: shop.acme.example
      http:
        paths:
          - {path: /, pathType: Prefix, backend: {service: {name: checkout-api, port: {number: 80}}}}
          - {path: /search, pathType: Prefix, backend: {service: {name: search, port: {number: 9200}}}}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: search}
spec:
  template:
    spec:
      containers:
        - name: search
          env:
            - {name: CATALOG_URL, value: "http://catalog.prod.svc.cluster.local:8080"}
---
apiVersion: v1
kind: Service
metadata: {name: catalog}
"""

INFRA_HELM = """\
search:
  cacheHost: redis-main
catalog:
  databaseUrl: postgres-inv
redis-main:
  image: redis
postgres-inv:
  image: postgres
"""

SAMPLE_FILES = [
    ("acme/checkout", "docker-compose.yml", CHECKOUT_COMPOSE),
    ("acme/payments", "docker-compose.yml", PAYMENTS_COMPOSE),
    ("acme/payments", ".env", PAYMENTS_ENV),
    ("acme/infra", "k8s/web.yaml", INFRA_K8S),
    ("acme/infra", "charts/shop/values.yaml", INFRA_HELM),
]
