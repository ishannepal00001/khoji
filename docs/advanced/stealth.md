# Stealth and anti-bot behaviour

> **Level:** advanced · **Prerequisites:** [Configuration](../guides/configuration.md)

This page explains what khoji does to look like a person's browser, what it deliberately leaves
alone, and what you can do to improve your odds on strict sites.

- [How sites detect bots](#how-sites-detect-bots)
- [What khoji does](#what-khoji-does)
- [What khoji deliberately does not do](#what-khoji-deliberately-does-not-do)
- [Your part](#your-part)
- [What khoji cannot do](#what-khoji-cannot-do)

## How sites detect bots

Detection vendors (Cloudflare, DataDome, Akamai, PerimeterX, Imperva) combine many signals:

| Layer | Examples |
|---|---|
| **Automation leaks** | `navigator.webdriver`, CDP traces, injected globals |
| **Fingerprint** | Browser build, fonts, GPU, screen and window sizes, and whether they agree with each other |
| **Network** | IP reputation (datacenter vs residential), TLS fingerprint, request rate |
| **Behaviour** | Mouse movement, scrolling, typing rhythm, time on page |
| **Consistency** | Timezone vs IP location, locale vs `Accept-Language`, user agent vs platform |

The theme: a real browser is *consistent*. Most detection looks for something that does not add up.

## What khoji does

| Measure | How |
|---|---|
| Removes automation leaks | Built on Patchright, a patched Playwright that hides CDP and `webdriver` traces |
| Uses a common fingerprint | Picks installed Google Chrome over the bundled Chromium |
| Keeps a real history | Always a persistent profile, so cookies and site trust build up over time |
| Headed by default | `headless=False`; headless browsers differ in many detectable ways |
| Natural viewport | No fixed viewport (`no_viewport`); the page size follows the window |
| Human scrolling | `scroll_to_end()` uses mouse-wheel events with jittered steps and random pauses |
| Human typing | Chat `send()` types key by key with uneven delays and thinking pauses |
| Human polling | Chat waits poll at random intervals, not on a fixed clock |
| Patience with challenges | Waits up to `challenge_wait_ms` for a non-interactive challenge to clear by itself |

## What khoji deliberately does not do

**It does not let you set the user agent, headers or viewport.** This is the most common
mistake in scraping tools. A spoofed user agent claims one browser and platform while the TLS
handshake, JavaScript APIs and fonts reveal another. That mismatch is a stronger signal than the
true value would have been. khoji keeps whatever the real browser reports.

**It does not rotate fingerprints.** One consistent identity per profile looks like a returning
visitor. A new random fingerprint every visit looks like nobody.

**It does not solve CAPTCHAs.** Interactive challenges need a person.

## Your part

The library covers the browser. The rest is up to how you use it.

1. **Use real Chrome.** Install it; khoji picks it up automatically.
2. **Stay headed.** Use `xvfb-run` on servers instead of `headless=True`.
3. **Go slow.** Pause between pages. A person does not load 50 pages a minute.
4. **Use good IPs.** Datacenter IPs are often blocked outright. Residential or mobile proxies
   work better on strict sites.
5. **Be consistent.** Set `locale` and `timezone_id` to match the proxy's location.
6. **Warm up the profile.** Open the site by hand once in the profile (khoji runs headed, so
   you can just use the window), accept cookies, pass any challenge. The profile remembers.
7. **One identity per profile.** Do not share a profile between accounts or regions.
8. **Reuse the profile.** A profile with history is more trusted than a fresh one.

## What khoji cannot do

- Pass interactive CAPTCHAs.
- Hide a bad IP. If the IP is flagged, no browser trick helps.
- Make scraping allowed. Blocks are often the site telling you no; respect it.

---

**Related:** [Configuration](../guides/configuration.md) ·
[Errors and debugging](../guides/errors-and-debugging.md#blockederror)
