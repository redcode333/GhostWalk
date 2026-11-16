# INC-1020: cart counter wrong on the storefront

Root cause: redis-cart, evictions under memory pressure.
Path: redis-cart -> cart-api -> web.
What the map missed: the web app reads the cart count from redis-cart through a shared cache helper, so web depends on redis-cart directly.
