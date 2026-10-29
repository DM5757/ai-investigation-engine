---
title: Incident Report — Payment Outage March
author: Alex Chen
date: 2024-03-15
---
# Incident Report — Payment Outage March

## Summary

PaymentService timed out for six hours on 2024-03-12 after the **auth-gateway** deploy at 08:10 UTC.

## Impact

Card authorizations failed; SettlementBatch lagged by 4 hours.

## Root cause (ops claim)

A misconfigured JWT TTL on AuthGateway caused cascading retries into PaymentService.
