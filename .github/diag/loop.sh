#!/bin/bash
# Throwaway: loop media+convert tests; on a stuck spawned child, sample it.
LOOPS=${LOOPS:-12}
hangs=0
for i in $(seq 1 "$LOOPS"); do
  echo "=== loop $i"
  uv run --group test pytest -p no:timeout -q -x -p no:cacheprovider tests/media_utils tests/pipeline/test_convert.py > "out-$i.log" 2>&1 &
  uvpid=$!
  while kill -0 $uvpid 2>/dev/null; do
    sleep 5
    py=$(pgrep -P $uvpid | head -1)
    [ -z "$py" ] && continue
    for c in $(pgrep -P "$py"); do
      et=$(ps -o etime= -p "$c" | tr -d ' ')
      secs=$(echo "$et" | awk -F: '{ if (NF==2) print $1*60+$2; else if (NF==3) print $1*3600+$2*60+$3; else print $1 }')
      if [ "${secs:-0}" -ge 60 ]; then
        echo "!!! HANG loop $i: child $c of pytest $py, etime $et"
        ps -ax -o pid,ppid,pgid,stat,etime,wchan,command | awk -v p="$py" '$1==p || $2==p || $3==p'
        ps -M -p "$c"
        echo "--- sample child"; sample "$c" 3 2>&1 | head -120
        echo "--- sample pytest"; sample "$py" 3 2>&1 | grep -v "^ *$" | head -200
        echo "--- lsof child"; lsof -p "$c" 2>&1 | head -60
        echo "--- tail of pytest output"; tail -5 "out-$i.log"
        hangs=$((hangs+1))
        kill -9 "$c" "$py" 2>/dev/null
        break 2
      fi
    done
  done
  wait $uvpid; echo "loop $i exit $?: $(tail -1 out-$i.log)"
done
echo "HANGS: $hangs"
[ $hangs -eq 0 ]
