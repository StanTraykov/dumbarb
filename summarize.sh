# !/usr/bin/env bash
file=${1?"usage: summarize <dumbarb-output-file>"}
if ! [ -f "$file" ]; then
    echo "$file does not exist or is not a regular file."
    exit 1
fi

#wins
gawk '{
    tmv+=$10; mvmax=($10>mvmax?$10:mvmax);mvmin=($10<mvmin||mvmin==0?$10:mvmin)

    ++t; p1=$3; p2=$5; if($4=="W")p1W++; if($6=="W")p2W++; if($4=="B")p1B++; if($6=="W")p2B++;
    if($8==p1)p1wins++; if($8==p1&&$4=="W")p1winsW++; if($8==p1&&$4=="B")p1winsB++;
    if($8==p2)p2wins++; if($8==p2&&$6=="W")p2winsW++; if($8==p2&&$6=="B")p2winsB++;

    p1mv+=$11; p2mv+=$12; p1tt+=$13; p2tt+=$16;
    p1mtm=($15>p1mtm?$15:p1mtm); p2mtm=($18>p2mtm?$18:p2mtm);
    }
    END{
        printf "%d total games, %d total moves,  %.2f avg moves/game, %d min, %d max\n",
            t, tmv, tmv/t, mvmin, mvmax;

        printf "%s: %d wins, %d wins from %d total as W, %d wins from %d total as B\n",
            p1, p1wins, p1winsW, p1W, p1winsB, p1B;
        printf "%s: %d wins, %d wins from %d total as W, %d wins from %d total as B\n",
            p2, p2wins, p2winsW, p2W, p2winsB, p2B;

        printf "%s: %f total thinking time, %f avg/move, %f max\n",
            p1, p1tt, p1tt/p1mv, p1mtm;
        printf "%s: %f total thinking time, %f avg/move, %f max\n",
            p2, p2tt, p2tt/p2mv, p2mtm;

    }'  $file

