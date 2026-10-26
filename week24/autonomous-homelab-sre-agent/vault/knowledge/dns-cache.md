# DNS cache runbook

## Netflix fixture record

The expected synthetic `netflix.com` address is `198.51.100.30`. The `203.0.113.0/24` range is reserved for documentation and is an obsolete target in these fixtures. Compare the lookup result with the expected address and a matching `DNS_STALE_TARGET` event.

## Cache verification

After an approved simulated cache flush, repeat the lookup and confirm that it returns the current fixture address. This runbook describes local fixture data; it does not authorize a real resolver change.
