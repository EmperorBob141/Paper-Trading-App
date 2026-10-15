# KJP Paper Trader

A locally run paper trading website. Each account starts with $100,000 in paper money to trade real
US stocks and ETFs at Yahoo Finance's free, roughly 15-minute delayed prices.

## Run it

Double-click **start.bat**. The first run sets everything up (about a minute), then your browser opens
at http://localhost:8000. Keep the black window open while you use the site; close it to stop.

## Where your data lives

Accounts, holdings and every trade are saved in `data/paper_trading.db`. That file is all you need to
keep; back it up if you want a copy. Deleting it resets everything.

## How orders work

Orders only execute during regular market hours: 8:30 am to 3 pm Central Time (9:30 am to 4 pm Eastern),
Monday to Friday, closed on NYSE holidays and closing at noon Central on early-close days. Prices and price
changes only count regular-hours trading; pre-market and after-hours moves are ignored. Times in the app
are shown in Central Time.

- **Market orders** fill instantly at the latest delayed quote while the market is open. Placed while it
  is closed, they are queued and fill at the next session's opening price. You can cancel a queued order
  from "Queued orders" on the Portfolio page or the stock's page.
- **Limit orders** fill when the price reaches your limit during market hours: a buy at the limit or lower,
  a sell at the limit or higher. They are checked against Yahoo's minute-by-minute prices since you placed
  them, so an order still fills if the price got there while the app was closed. Choose "Until canceled" or
  "End of day" (expires at that session's close). While a buy is pending its cost is held from your buying
  power; while a sell is pending its shares are held.

You can buy or sell by share count or by dollar amount; fractional shares are supported.

## Quarterly deposits

Every 3 months, 2% of your account value is added to your cash on the 1st of the month. The first deposit
is on the 1st of the month three months after the month you opened the account (opened Oct 15, first deposit
Jan 1), then Apr 1, Jul 1, Oct 1 and so on. The amount is 2% of your account value at the last market close
before the payout date. If the app was closed on a payout date, the deposit is added the next time it runs.
Deposits raise your account value but don't count as gains in your returns or the market comparison.

## Dividends

Dividends count toward your returns and show up in the Dividend income section of the Performance page.
Choose how you receive them there:

- **Cash**: the dividend is added to your cash on the ex-dividend date.
- **Reinvest** (the default): the dividend buys more shares of the stock that paid it, at that day's closing price.
  These purchases are listed as "Dividend reinvested" in History.

Changing the choice applies to dividends from then on; past dividends stay as they were.

## Changing the website code

The site in `frontend/dist` is already built. If you edit files in `frontend/src`, rebuild with:

    cd frontend
    npm install
    npm run build

Or, for live reload while editing, run `start.bat` in one window and `npm run dev` in `frontend` in
another, then open http://localhost:5173.
