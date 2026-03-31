#!/bin/bash
# Setup GitHub labels for AuroraTape/aurora-ltfs
# Based on TagDefinitions.xlsx
#
# Smart sync: keep exact matches, rename code matches, delete unknown, create missing.
#
# Usage: gh auth login && bash setup-labels.sh

REPO="AuroraTape/aurora-ltfs"

# --- Define desired labels ---
# Format: "name|color|description"
DESIRED_LABELS=(
  # Originator (Who/When)
  '[00] Test|ffffff|Incident opened by test team'
  '[01] Dev|ffffff|Opened by development by ourselves'
  '[02] Question|ffffff|Internal question to dev team'
  '[03] Cust. Prob|ffffff|Problem reported from customer'
  '[04] Cust. Req|ffffff|Request from customer'
  '[05] Cust. Question|ffffff|Question from customer'
  '[06] Pt. Prob|ffffff|Problem reported from business partner'
  '[07] Pt. Req|ffffff|Request from business partner'
  '[08] Pt. Question|ffffff|Question from business partner'
  # Severity/Symptom
  '[100] Data loss (999)|d50000|Data is corrupted and not functional (unrecoverable)'
  '[101] Data integrity (900)|ff0000|Running with incorrectly overwritten data (unrecoverable)'
  '[200] Data inaccessible (850)|ff8000|Data exists but inaccessible for some reason (recoverable)'
  '[201] Crash (800)|ff952b|Process crash (recoverable)'
  '[202] Hangup (750)|ffaa55|Process hang (infinite loop, deadlock, etc.)'
  '[203] Resource leak (720)|ffaa55|Resource leak (memory, file descriptor, etc.)'
  '[204] Unstartable (700)|ffbf80|Server/client fails to start'
  '[205] Unused (600)|ffd5aa|Unused'
  '[300] Incorrect result (500)|b1b123|Returns unexpected results'
  '[301] Unexpected behavior (450)|d5d52b|Unexpected behavior other than results'
  '[302] Too long time (420)|dcdc4e|Execution time is too long'
  '[303] Missing function (400)|e2e272|Function is not provided'
  '[400] Incorrect output (100)|eaea95|Display is incorrect'
  '[401] Incorrect Document (100)|eaea95|Document description is incorrect'
  '[402] Incorrect log (100)|eaea95|Log output is incorrect'
  '[403] Inadequate output (50)|eaea95|Display is insufficient'
  '[404] Inadequate document (50)|eaea95|Document is insufficient'
  '[405] Inadequate log (50)|eaea95|Log output is insufficient'
  # Probability
  '[800] Always (100)|8d6a47|Reproduces 100% in a given scenario'
  '[801] Usually (90)|aa8055|Reproduces ~90% in a given scenario'
  '[802] Often (75)|b89572|Reproduces ~75% in a given scenario'
  '[803] Sometimes (50)|c7aa8d|Reproduces ~50% in a given scenario'
  '[804] Occasionally (25)|d5bfaa|Reproduces ~25% in a given scenario'
  '[805] Rarely (10)|e2d5c7|Reproduces ~10% in a given scenario'
  '[806] One shot (1)|e2d5c7|Reproduced only once'
  # Impact
  '[900] Imp. Huge|723855|Blocks execution of all test cases'
  '[901] Imp. Big|8d476a|Blocks 10 or more test cases'
  '[902] Imp. Middle|aa5580|Blocks multiple test cases'
  '[903] Imp. Small|b87295|Blocks the target test case'
  '[904] Imp. Tiny|c78daa|Blocks the target scenario of the target test case'
  '[905] Imp. None|d5aabf|No test case blocking'
  # Priority
  '[P01] Anchor|00ff80|Anchor item for current development (required for GA)'
  '[P02] Pri. High|55ffaa|Required feature for current development'
  '[P03] Pri. Mid|80ffbf|Should be included in current development'
  '[P04] Pri. Low|aaffd5|Include in current development if possible'
  '[P99] Defer|d5ffea|Deferred to next development cycle'
  # Analysis Result
  '[A00] Code|d5ffff|Fix the code'
  '[A01] Enhancement|d5ffff|Process as enhancement request'
  '[A02] New Feature|d5ffff|New feature'
  '[A03] Log/Msg|d5ffff|Fix log or message'
  '[A04] Document|d5ffff|Fix documentation'
  '[A05] More Info|eaffff|(Return) Report content is incomplete'
  '[A06] As expected|eaffff|(Return) Behaving as expected'
  '[A07] Duplicate|eaffff|(Return) Already reported issue'
  '[A08] Invalid|eaffff|(Return) Test itself is invalid (incorrect scenario or test method)'
  '[A99] Wontfix|f4ffff|Problem acknowledged but impact is minor, will not fix for now'
  # Miscellaneous
  '[Z01] Experiment|b4b4b4|Experiment and report'
  '[Z02] Good first issue|b4b4b4|Good for newcomers'
  '[Z03] Backlog|b4b4b4|To be considered later'
  '[Z04] Help wanted|b4b4b4|Extra attention is needed'
  # Attention
  '!!!HOT!!!|ff00ff|Item causing issues at customer site'
)

# --- Extract code from label name ---
# e.g. "[100] Data loss (999)" -> "100"
#      "[P01] Anchor"          -> "P01"
#      "[A99] Wontfix"         -> "A99"
#      "!!!HOT!!!"             -> ""  (no code)
extract_code() {
  local name="$1"
  if [[ "$name" =~ ^\[([A-Z0-9]+)\] ]]; then
    echo "${BASH_REMATCH[1]}"
  fi
}

# --- Fetch existing labels ---
echo "Fetching existing labels..."
EXISTING_JSON=$(gh label list --repo "$REPO" --limit 200 --json name,color,description)
mapfile -t EXISTING_NAMES < <(echo "$EXISTING_JSON" | jq -r '.[].name')

echo "Found ${#EXISTING_NAMES[@]} existing labels."
echo ""

# --- Build lookup: code -> desired name ---
declare -A DESIRED_BY_CODE    # code -> name
declare -A DESIRED_BY_NAME    # name -> "color|description"
declare -A DESIRED_NAMES_SET  # name -> 1

for entry in "${DESIRED_LABELS[@]}"; do
  IFS='|' read -r d_name d_color d_desc <<< "$entry"
  code=$(extract_code "$d_name")
  if [[ -n "$code" ]]; then
    DESIRED_BY_CODE["$code"]="$d_name"
  fi
  DESIRED_BY_NAME["$d_name"]="$d_color|$d_desc"
  DESIRED_NAMES_SET["$d_name"]=1
done

# --- Build lookup: code -> existing name ---
declare -A EXISTING_BY_CODE   # code -> name
declare -A PROCESSED          # existing name -> 1 (handled)

for ename in "${EXISTING_NAMES[@]}"; do
  code=$(extract_code "$ename")
  if [[ -n "$code" ]]; then
    EXISTING_BY_CODE["$code"]="$ename"
  fi
done

# --- Process each desired label ---
for entry in "${DESIRED_LABELS[@]}"; do
  IFS='|' read -r d_name d_color d_desc <<< "$entry"
  code=$(extract_code "$d_name")

  # Check if exact name already exists
  found_exact=false
  for ename in "${EXISTING_NAMES[@]}"; do
    if [[ "$ename" == "$d_name" ]]; then
      found_exact=true
      break
    fi
  done

  if $found_exact; then
    # Exact match: update color/description only
    echo "KEEP:   $d_name (update color/description)"
    gh label edit "$d_name" --repo "$REPO" --color "$d_color" --description "$d_desc" 2>/dev/null
    PROCESSED["$d_name"]=1
  elif [[ -n "$code" ]] && [[ -n "${EXISTING_BY_CODE[$code]}" ]]; then
    # Code match but different name: rename
    old_name="${EXISTING_BY_CODE[$code]}"
    echo "RENAME: $old_name -> $d_name"
    gh label edit "$old_name" --repo "$REPO" --name "$d_name" --color "$d_color" --description "$d_desc" 2>/dev/null
    PROCESSED["$old_name"]=1
  else
    # No match: create new
    echo "CREATE: $d_name"
    gh label create "$d_name" --repo "$REPO" --color "$d_color" --description "$d_desc" 2>/dev/null
  fi
done

# --- Delete existing labels not in desired set ---
echo ""
echo "Cleaning up labels not in the definition..."
for ename in "${EXISTING_NAMES[@]}"; do
  if [[ -z "${PROCESSED[$ename]}" ]] && [[ -z "${DESIRED_NAMES_SET[$ename]}" ]]; then
    echo "DELETE: $ename"
    gh label delete "$ename" --repo "$REPO" --yes 2>/dev/null
  fi
done

echo ""
echo "Done! Label sync complete."
