---
applyTo: '**/*.py'
---
The code being written is a Python script that processes NFL data and tries to give me the best NFL fantasy lineup based on the data provided. This is my league's scoring system: 

**Offense Scoring**

* Passing Yards: **1 point per 25 yards**
* Passing Touchdowns: **+4 points**
* Interceptions Thrown: **-2 points**
* Rushing Yards: **1 point per 10 yards**
* Rushing Touchdowns: **+6 points**
* Receptions: **+1 point each** (PPR)
* Receiving Yards: **1 point per 10 yards**
* Receiving Touchdowns: **+5 points**
* Return Yards: **1 point per 25 yards**
* Return Touchdowns: **+6 points**
* 2-Point Conversions: **+2 points**
* Fumbles Lost: **-2 points**
* Offensive Fumble Return Touchdown: **+6 points**


**Kicker Scoring**

* Field Goals Missed (0–19 yards): **-1 point**
* Field Goals Missed (20–29 yards): **-1 point**
* Field Goals Missed (30–39 yards): **-1 point**
* Field Goals Missed (40–49 yards): **-1 point**
* Field Goals Missed (50+ yards): **-1 point**
* Point After Attempt Made: **+1 point**
* Point After Attempt Missed: **-1 point**
* Field Goal Yards: **1 point per 10 total yards**

**Defense/Special Teams (DST) Scoring**

* Sack: **+1 point**
* Interception: **+2 points**
* Fumble Recovery: **+2 points**
* Touchdown: **+6 points**
* Safety: **+2 points**
* Block Kick: **+2 points**
* Kickoff or Punt Return Touchdown: **+6 points**
* Points Allowed:

  * 0 points allowed: **+10 points**
  * 1–6 points allowed: **+7 points**
  * 7–13 points allowed: **+4 points**
  * 14–20 points allowed: **+1 point**
  * 21–27 points allowed: **0 points**
  * 28–34 points allowed: **-1 point**
  * 35+ points allowed: **-4 points**
* Extra Point Returned: **+2 points**

Need to basically optimize for the best lineup based on the above scoring system. The script should be able to read player data, calculate their projected points based on the scoring system, and then select the optimal lineup while adhering to roster constraints (e.g., number of players per position).
Positions in the lineup are as follows:
QB, WR, WR, RB, RB, TE, W/R/T, K, DEF, BN, BN, BN, BN, BN