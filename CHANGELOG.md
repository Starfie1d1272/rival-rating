# @rivalhub/rival-rating

## 0.2.0

### Minor Changes

- Promote RR to the six-account model and clean up old intermediate exports.

  - Replace the old value-accounts v2 lite model with `computeRRSixAccounts` and `rrSixAccountsModel`.
  - Add the `RRSignals` six-account contract with MapControl, spatial Utility, and `strategicIsolationDeaths`.
  - Rename HLTV 2.0 baseline weights to `hltv-2-baseline-v1.json` and export them as `hltv2BaselineWeightsV1`.
  - Add conservative first-pass RR weight calibration with `score.base`, `score.scale`, per-round caps, lower non-Combat priors, and clutch shrinkage.
  - Improve PRISM no-signal handling with `hasSignal` and `availableSignalWeight`.

  Breaking changes:

  - Removed old public exports for `AccountSignalsV2`, `ValueAccountsWeights`, `RRResultV2`, `computeValueAccountsRR`, `computeLeagueMeanV2`, `valueAccountsV2LiteModel`, `rrWeightsV1`, and `rrValueAccountsV2Lite`.
  - Use `RRSignals`, `RRSixAccountWeights`, `RRSixAccountResult`, `computeRRSixAccounts`, `computeRRSixAccountMean`, `rrSixAccountsModel`, `hltv2BaselineWeightsV1`, and `rrSixAccountWeightsV1` instead.
