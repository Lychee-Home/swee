# Changelog

## [2.10.0](https://github.com/Lychee-Home/swee/compare/v2.9.0...v2.10.0) (2026-07-21)


### Features

* color palfeed embeds by IV tier ([#56](https://github.com/Lychee-Home/swee/issues/56)) ([01a09ef](https://github.com/Lychee-Home/swee/commit/01a09ef07866eed7feac8623ecb1c70dc5a92291))
* restructure palfeed embed as IV% and Stats fields ([#55](https://github.com/Lychee-Home/swee/issues/55)) ([8e1d98e](https://github.com/Lychee-Home/swee/commit/8e1d98e45f4a5e52c5726ea321bcaef88a956c9c))
* show acquired_at as the palfeed embed timestamp ([#57](https://github.com/Lychee-Home/swee/issues/57)) ([cb8cdf3](https://github.com/Lychee-Home/swee/commit/cb8cdf3f07c2aec165aedf0a9d012093b51026d2))
* show palfeed IV total as a percentage ([#54](https://github.com/Lychee-Home/swee/issues/54)) ([a3d53ad](https://github.com/Lychee-Home/swee/commit/a3d53ad6a8136fe9dec3a7142adfcf7a5ef9a79e))


### Bug Fixes

* reword palfeed embed title to describe IVs, not the Pal ([#52](https://github.com/Lychee-Home/swee/issues/52)) ([58c529a](https://github.com/Lychee-Home/swee/commit/58c529a6092cb24991b54a8a3a93388f60c957a6))

## [2.9.0](https://github.com/Lychee-Home/swee/compare/v2.8.0...v2.9.0) (2026-07-21)


### Features

* use palsave-api's resolved pal display name in palfeed embeds ([#50](https://github.com/Lychee-Home/swee/issues/50)) ([7d5bb38](https://github.com/Lychee-Home/swee/commit/7d5bb38a2f0d62c32c48984e9c9aa15fce3e40b3))

## [2.8.0](https://github.com/Lychee-Home/swee/compare/v2.7.0...v2.8.0) (2026-07-21)


### Features

* pal-catch recap feed (palfeed) ([#48](https://github.com/Lychee-Home/swee/issues/48)) ([18dba49](https://github.com/Lychee-Home/swee/commit/18dba493cef3368d202a9d8195d4808939810405))
* per-player conversation sessions for [@swee](https://github.com/swee) assistant ([#47](https://github.com/Lychee-Home/swee/issues/47)) ([9b9f735](https://github.com/Lychee-Home/swee/commit/9b9f735a29ef4216b2ea3ea46f1915d0c83f3fcd))


### Bug Fixes

* style in-game assistant reply prefix as [swee] ([#44](https://github.com/Lychee-Home/swee/issues/44)) ([530df23](https://github.com/Lychee-Home/swee/commit/530df23bfb5e0423e7885467e444f9ac832799af))

## [2.7.0](https://github.com/Lychee-Home/swee/compare/v2.6.0...v2.7.0) (2026-07-17)


### Features

* in-game [@swee](https://github.com/swee) Palworld Q&A assistant ([#39](https://github.com/Lychee-Home/swee/issues/39)) ([7ee21b4](https://github.com/Lychee-Home/swee/commit/7ee21b45bdc146762c809d8f825457d8d09549ad))
* persist session_started across bot restarts ([#43](https://github.com/Lychee-Home/swee/issues/43)) ([4680287](https://github.com/Lychee-Home/swee/commit/4680287567a9d2954dd93ecbcb7083aba9dbdf90))


### Bug Fixes

* key pending-connect fallback by Steam user id, not display name ([#41](https://github.com/Lychee-Home/swee/issues/41)) ([6577967](https://github.com/Lychee-Home/swee/commit/65779675408e2cefb0576bf967a42443006226e9))
* use GitHub's published_at for release embed timestamp ([#42](https://github.com/Lychee-Home/swee/issues/42)) ([c2aa315](https://github.com/Lychee-Home/swee/commit/c2aa315ac463a76bdef3b5e2c04d9bb74143f1be))

## [2.6.0](https://github.com/Lychee-Home/swee/compare/v2.5.0...v2.6.0) (2026-07-17)


### Features

* announce every missed GitHub release, not just the newest ([#37](https://github.com/Lychee-Home/swee/issues/37)) ([a337069](https://github.com/Lychee-Home/swee/commit/a337069b7515814e821f01f025832386a4a40c82))
* show system RAM as percentage only ([#38](https://github.com/Lychee-Home/swee/issues/38)) ([4b74572](https://github.com/Lychee-Home/swee/commit/4b745726e117e43ed4355f075c4a1697b1c50b46))


### Bug Fixes

* strip PR/commit links from release announcements ([#35](https://github.com/Lychee-Home/swee/issues/35)) ([15c7ce8](https://github.com/Lychee-Home/swee/commit/15c7ce8ec79fa75f2b597f2f505b37ab650094d7))

## [2.5.0](https://github.com/Lychee-Home/swee/compare/v2.4.0...v2.5.0) (2026-07-17)


### Features

* broadcast in-game warning and delay before /restart and /update ([#31](https://github.com/Lychee-Home/swee/issues/31)) ([d8bc002](https://github.com/Lychee-Home/swee/commit/d8bc0024a9da15c8d50aefb8e2d7ba993b797606))
* make GITHUB_REPO optional ([#29](https://github.com/Lychee-Home/swee/issues/29)) ([8d6d6ff](https://github.com/Lychee-Home/swee/commit/8d6d6ff2f4bd4f6c3146c9eac70470e716459ed8))
* show in-game day count in stats embed ([#34](https://github.com/Lychee-Home/swee/issues/34)) ([2969f31](https://github.com/Lychee-Home/swee/commit/2969f3113deeeece16394ca6368b937e4a25528e))
* show system CPU usage in the stats embed ([#32](https://github.com/Lychee-Home/swee/issues/32)) ([a6c185c](https://github.com/Lychee-Home/swee/commit/a6c185c203386269f241a5f8ab6d6371bdaf697b))


### Bug Fixes

* add fallback join notification for missed 'joined the server' log lines ([#33](https://github.com/Lychee-Home/swee/issues/33)) ([b41369d](https://github.com/Lychee-Home/swee/commit/b41369da8322621296885d5ab91888fe5a0250b7))
