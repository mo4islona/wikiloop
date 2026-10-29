# Slow orders

1. Compare `checkout_request_duration_seconds` p99 per cluster. One cluster: go to step 2.
   Both: go to step 3.
2. Read `payments_request_duration_seconds` in that cluster. If it moved with checkout, the
   cause is payments; the payments team owns the next step.
3. Both clusters at once is an upstream dependency or a release: read the deploy history of
   checkout and payments for the last hour.
