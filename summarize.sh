# !/usr/bin/env bash
file=${1?"usage: summarize <dumbarb-output-file>"}
if ! [ -f "$file" ]; then
    echo "$file does not exist or is not a regular file."
    exit 1
fi

#wins
gawk '{
    tmv+=$9; mvmax=($9>mvmax?$9:mvmax);mvmin=($9<mvmin||mvmin==0?$9:mvmin)

    ++t; p1=$2; p2=$4; if($3=="W")p1W++; if($5=="W")p2W++; if($3=="B")p1B++; if($5=="W")p2B++;
    if($7==p1)p1wins++; if($7==p1&&$3=="W")p1winsW++; if($7==p1&&$3=="B")p1winsB++;
    if($7==p2)p2wins++; if($7==p2&&$5=="W")p2winsW++; if($7==p2&&$5=="B")p2winsB++;

    p1mv+=$10; p2mv+=$11; p1tt+=$12; p2tt+=$15;
    p1mtm=($14>p1mtm?$14:p1mtm); p2mtm=($17>p2mtm?$17:p2mtm);
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

