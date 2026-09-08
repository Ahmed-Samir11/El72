
1- Yaoota search engine:
 793k followers (Whoa) on Facebook (latest post was in 2024)
The website gives a 503 service unavailable
2- Kanbkam:

15k followers on Facebook (latest post was in 2022)
Far more categories than Elhaq, but only track items from Jumia, Amazon, and Noon.
They show the exact price of the item in the stores, so idk think they are taking a percentage of the price of the items from the stores. They could still have an Affiliate & lead gen model where they get commission for buying customers. 

1. Localizing the Business Model for the Egyptian Community
To make EL72 successful in Egypt, we have to build trust and solve local friction points.

1- The Trust Deficit (The "Sub" Phenomenon): Egyptian consumers are highly skeptical of automated online platforms due to outdated listings or fake discounts. Anomaly detection can help with that. We shouldn't just track price drops; it needs to filter out "bait-and-switch" tactics (e.g., a store listing a 5080 at 50k EGP, but it’s actually out of stock or requires a bundle purchase).

2- Leveraging WhatsApp Effectively: Email open rates are notoriously low in Egypt, but everyone lives on WhatsApp. However, WhatsApp Business API costs can scale quickly. We’'ll need to optimize our Redis event streams so it only fire a WhatsApp notification when a high-confidence, verified deal hits the user’s exact sweet spot, saving API overhead.

Meta splits messages into 4 categories. For EL72, choosing the right template category will dictate our operating margin (new term whoa) (percentage of revenue left over after paying for core day-to-day operating expenses ).


Category
Typical Use for Elhaq
Cost Per Message (USD)
Cost in EGP (approx.)
Utility
"Your tracked 5080 GPU dropped to 78k EGP."
$0.0036
~0.17 EGP
Authentication
Signing up / Verification OTP codes.
$0.0036
~0.17 EGP
Marketing
"Welcome to El72! Check out today's top 10 price drops!
$0.1073
~5.20 EGP
Service
User messages you first (e.g., "Check status of item").
FREE (Within 24 hours)
0.00 EGP


3. Hacks to Keep Costs Near Zero
Since we are managing this via Redis Streams, we can build constraints to manipulate Meta’s pricing laws to our advantage:
Aggressive Rate Limiting: If a store’s price bounces up and down by 100 EGP rapidly, it could trigger a stream loop that fires 20 messages an hour to a user, costing us money, and ts could get our number banned for spam. Restrict non-premium users to a maximum of 1 alert per item per day.
In research for more




Meta’s Rule of Thumb: Transaction vs. Promotion
Meta decides the category based on the primary trigger of the message:
Marketing: A broadcast initiated by you to push a sale, cross-sell, or re-engage an idle user (e.g., "Hey, we have a flash sale on graphics cards today!").
Utility: An update directly triggered by a specific, pre-agreed action taken by the user (e.g., checking an order status, an account balance update, or a custom alert they explicitly asked to receive).
Because your user opened Elhaq, explicitly selected an item, set a specific price range, and turned on notifications for it, the resulting alert is legally classified as a transactional notification/custom alert. You are simply delivering the data the user requested.
The Danger Zone: How to Avoid Auto-Reclassification
Meta uses automated ML classifiers to read your templates during submission. If you include even one sales-pitch word, their system will automatically reclassify it as a Marketing template and charge you the high rate.
To keep it strictly in the Utility bucket, your templates must be completely neutral, informational, and directly tie back to the user's explicit action.
❌ What gets rejected or forced into "Marketing"
"Good news! The RTX 5080 just dropped to 78,000 EGP at El-Bostan Tech! Buy it now before stock runs out and get a free mousepad! Click here: [Link]"
Why it fails: Words like "Good news", "Buy it now", "before stock runs out", and offering a "free mousepad" are promotional/persuasive language.
What gets approved instantly as "Utility"
"Elhaq Alert: The item you are tracking ({{1}}) has entered your requested price range. Current price: {{2}} EGP. View details: {{3}}"
Why it passes: The tone is completely neutral, operational, and references the user's ongoing transaction ("the item you are tracking"). It contains no adjectives, no hype, and no sales pressure.

Ts from Gemini    abobobobob

Business Revenue Models Ideas
Kanbkam used Affiliate & Lead Gen: Merchant pays you a percentage (1-3%) when a user clicks your WhatsApp link and buys. For local physical shops, charge a flat "Lead Fee" for sending a verified buyer.
 
Now with the suggestions(maaaaan ts needs to be studied)
1. The Token/Credit System (The "Pay-As-You-Track" Model)(Good)
Instead of a monthly subscription, users buy a package of "Tracking Credits" (e.g., 20 EGP for 5 tracking credits via Vodafone Cash).
How it works: Tracking an item costs 1 credit per week or day (we should discuss ts). When a user runs out of credits, tracking pauses.
Why it works in Egypt: It mimics the culturally deeply embedded behavior of recharging Fakka cards. It gives the user absolute control with zero commitment.\
2. High-Priority "Fast-Lane" Premium (IDK kinda meh)
Everyone can track items for free, but free users get notifications on a 15-to-30-minute delay.
How it works: Premium users pay a flat micro-fee (e.g., 50 EGP/month) to get Instant Redis Stream Routing. The second the scraper detects the budget match, the WhatsApp message fires.
Why it works in Egypt: For high-demand, low-stock items like graphics cards, PlayStation consoles, or specific mobile phones, a 15-minute delay means the item is already sold out. Tech enthusiasts and resellers will gladly pay to be first.
3. Native Affiliate URL Stripping (Zero-Friction Free Tier) (ts is bad)
The app remains 100% free for the user, with no paid tiers at all. We shouldn’t use this one, it won’t work.
How it works: When a user sets a tracker for Amazon Egypt, Jumia, or Noon, our backend automatically strips the standard URL and replaces it with our platform's affiliate tracking tag. When they click the WhatsApp notification and buy, the e-commerce giant pays us a 1-7% commission.
Why it works in Egypt: The user experiences zero friction. Ts will fail and taint our image if the user searches for the item and finds it at a lower price.


4. Escrow Secured "Hold My Deal" Service (could be good, but not at the start)
High-ticket items found at massive discounts sell out within minutes, often before the user can physically log on or drive to the store.
How it works: Integrate an InstaPay/Fawry payment gateway. When a deal drops, the user can click a button on WhatsApp to instantly deposit a refundable down payment (e.g., 500 EGP) through our app to hold the item. We charge a small percentage of that deposit as a convenience fee.
Why it works in Egypt: Securing a highly liquid asset (like a cheap GPU or iPhone) instantly is a massive value add that buyers will willingly pay a premium for.

5. Installment-Brokering Micro-Commissions (ts is cool)
Since cash liquidity is tight, users want installment terms, but tracking down which bank or wallet has a "0% interest/0% down payment" promo on a specific item is incredibly difficult.
How it works: WhatsApp alert displays the item price alongside dynamic installment options (e.g., ValU, Aman, Soubool). If they opt to register or execute the payment plan via our link, we receive a customer acquisition payout from the financial provider.
Why it works in Egypt: We are providing a financial service directly to the consumer at the exact moment of high purchase intent, bypassing merchant suspicion entirely.
For this one, we should bear in mind the whatsapp api shit, as we could get flagged because of the price. We can arrange ts differently. Similar to a standard alert, it directs the user to the app and provides them with this as a ready alternative.
6. Tiered Pricing Value-Caps (ts was our initial revenue model)
A freemium model is directly tied to the monetary value of the item being tracked.
How it works:
Free Tier: Track items up to 5,000 EGP (clothes, groceries, basic accessories).
Mid Tier (30 EGP/mo): Track items up to 25,000 EGP (mid-range phones, monitors).
Max Tier (90 EGP/mo): Track high-ticket assets above 25,000 EGP (RTX 5080, laptops, appliances).
Why it works in Egypt: Psychologically, someone about to spend 80,000 EGP on a high-end graphics card will view a 90 EGP fee as completely negligible pocket change if it successfully saves them 5,000 to 10,000 EGP on their purchase.

6. The Blind Demand Data Feed (Aggregated Market Insights)
Retailers in Egypt struggle to guess how much inventory to import and at what price point.
How it works: You sell completely anonymized, aggregated dashboard access to big distributors or local chains. They can see demand graphs: "There are currently 4,200 unique users in Cairo tracking the RTX 5080 with a budget threshold between 75,000 and 78,000 EGP."
Why consumers won't suspect it: The user interface remains entirely untouched. Merchants never get access to individual user profiles, contact info, or identities—they are just buying aggregate market data.
7. Under-the-Hood Programmatic Affiliate Stripping
We remain impartial because we don’t pick partners; we let the platforms handle their own transactions.
How it works: When a user clicks a deal notification for Amazon Egypt, Noon, or Jumia, etc, our service automatically appends our enterprise tracking ID.
Why consumers won't suspect it: The user clicks the link and lands exactly on the native, trusted Amazon or Noon app. To them, Elhaq simply found the best deal on Amazon. They don't care that Amazon quietly routes a 2% to 5% cut of the transaction to our business account.
8. Still more to come









