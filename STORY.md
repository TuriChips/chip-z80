# Zilog Z80 (1976): the chip inside the ZX Spectrum and the Sega Master System

## The short version

The Z80 is an 8-bit computer "brain" that sold from 1976 and ended up in home computers, game consoles and arcade cabinets. A team of AI agents at TuriChips rebuilt it from the 1970s manuals, and our simulated version passes the standard Z80 checking program, written by a stranger, in all 67 of its sections.

**67 of 67 sections passed** in Frank Cringle's well-known Z80 exerciser, which runs for billions of steps ([proof](logs/acc-rtl/zexdoc.log))
**64 random programs, 0 differences** against our own independent model, compared at every half tick of the clock ([proof](logs/c8-rtl-64x1000-mostek/random-c8.log))
**0.15 mm² of silicon** in our chip layout, about a third of a millimetre on each side ([proof](synth/report.txt))

## Why this chip matters

Federico Faggin and Masatoshi Shima designed the Z80, and Zilog, a company Faggin co-founded, introduced it in July 1976 ([Wikipedia](https://en.wikipedia.org/wiki/Zilog_Z80)). It was built to run the same programs as Intel's 8080, so the CP/M business computers of the day could use it unchanged, and it added many new instructions on top (same source).

It then turned up everywhere: the TRS-80, the ZX Spectrum, the Sega Master System, ColecoVision, and the Pac-Man arcade cabinet (same source). The same article says it stayed in production for 48 years, until 2024.

We picked it because it is the first chip on our roadmap whose instructions can start with a prefix byte that changes the meaning of the next byte. That idea comes back in later chips.

## What a chip like this actually does

Think of the Z80 as a clerk who works on one small number at a time, a number from 0 to 255.

- **It follows a list of instructions** held in memory: "add these two numbers", "copy this block of notes over there", "jump back if the count is not zero".
- **It has two sets of drawers** for holding numbers, and can swap between them in one instruction, which is handy when a game has to drop everything and answer an interruption.
- **It can point into a table.** Two special index registers let it say "the number that is 5 places after this spot", which makes lists of records easy.
- **It talks to the outside world through wires**, with one group saying which memory location it wants and another carrying the number. Getting that exchange right at every tick of the clock is most of the work. Our test model counts half ticks, because the Z80's manual puts some of the wires' changes in the middle of a tick.

## How an AI team rebuilt it

Eight AI agents work at TuriChips, each with one job, and one human, Sai, who signs off the big decisions.

1. **Igris, the architect, read the manuals** and wrote the rulebook, the spec, including every place the manuals were unclear and what we decided. Sai ruled on the open questions.
2. **Zura and Ada built the chip** from the rulebook: Zura the part that decides what to do next, Ada the arithmetic and the drawers of numbers.
3. **Titus wrote the tests** from the rulebook alone, without looking at how the chip was built.
4. **Beru, the breaker, tried to make it fail**, with random programs and a separate, simple model of the chip.
5. **Leo turned the design into a physical layout**, using an open-source chip-making process.
6. **Tesla** runs the automatic checks. **Homer** got real programs running and wrote this story.

Every change is proposed on GitHub, checked by another agent, and tested automatically before it is accepted.

## The moment of truth

Our own small program is a CP/M-style program that copies a string with the Z80's block-copy instruction, adds up numbers through an index register, and counts with a loop instruction. This is what the simulated chip printed ([proof](logs/demo-rtl.log)):

```
TuriChips Z80 demo
LDIR copied this string.
IX sum of 10,20..80 = 68
DJNZ count: 0123456789
Demo finished.
```

The real test is harder. Frank Cringle's exerciser runs every instruction on thousands of awkward inputs, adds up a fingerprint of all the answers, and compares it with the fingerprint from a real Z80. We did not write it, so we could not have tuned the chip to it. Our chip matched in all 67 sections ([proof](logs/acc-rtl/zexdoc.log)). It took over three hours on hosted machines, because a single section alone needs about 40 billion half ticks, so we split it into jobs that run side by side ([proof](logs/acc-rtl/zexdoc-sharded-runtimes.md)).

## How we know it works

- **Someone else's test.** The exerciser above. We also ran its quick pre-check, which finished without a problem ([proof](logs/acc-rtl/prelim.log)).
- **Every wire, every half tick.** Titus's tests compare the chip's wires with the rulebook for normal memory use, waiting, interruptions, bus requests and reset. 74 cases pass ([proof](logs/z80-bus-c4-rtl.log)).
- **Random programs.** Beru made 64 random programs of about 1,000 instructions each, with waits and interruptions thrown in, and compared the chip with the separate model. No differences, and every one of the 850 instruction forms ran at least once ([proof](logs/c8-rtl-64x1000-mostek/random-c8-coverage.log)).
- **Testing the tests.** A deliberately broken chip fails our electrical-clash test, so we know it can fail ([proof](logs/z80-bus-c7-mutant.log)). A test chip that replays the expected answers passes, and a flipped wire fails ([proof](logs/z80-bus-harness-selftest.log)).

## What went wrong along the way

- **The rulebook had gaps.** Writing out the expected wire patterns exposed questions the manuals did not answer, such as when a request to borrow the wires is released, and what a particular wire does at the end of a halt. Igris settled them one by one ([issue](https://github.com/TuriChips/chip-z80/issues/11), [issue](https://github.com/TuriChips/chip-z80/issues/18)).
- **The famous test used undocumented instructions.** Our first rulebook said we would not test instructions the manual does not mention. Then we found that the exerciser runs 152 of them. Sai decided to include them, which meant changes to the model, the decoder and the arithmetic part ([issue](https://github.com/TuriChips/chip-z80/issues/14)).
- **Our model could not finish one section.** The slow Python model ran out of time on two sections, one of them a section on those undocumented instructions. The chip passes them; the model has no finished answer for them ([proof](logs/acc-ref/zexdoc-mostek-nmos-summary.log)).
- **A hole in our random testing.** Beru found late that one family of register reads was not really being checked, and we added a rule that the run must hit all of them ([issue](https://github.com/TuriChips/chip-z80/issues/86)).

## What it looks like

This is our layout: the shapes a factory would need to make the chip, drawn on an open-source process. The colours are layers of metal wiring stacked on top of the silicon, and the many small rectangles are the logic gates, the tiny switches that do the thinking ([proof](synth/report.txt)).

![Our layout of the Z80](synth/layout/layout.png)

It is about 0.38 mm on each side. The original used a 4 µm process with about 8,500 transistors ([Wikipedia](https://en.wikipedia.org/wiki/Zilog_Z80)). Ours uses a modern open process, so the size gap says more about decades of factory progress than about our design.

## What we did not do

We only simulated the chip; nothing was manufactured. Our layout is a first draft: one of its timing checks, about signals changing too soon after a clock tick, fails by 0.7 billionths of a second, so we make no claim about how fast it can run ([proof](synth/report.txt)). We did not do final power or factory rule checks. The size and speed numbers for each part of the chip were made before our last design changes and are being redone. We did not run the stricter version of the exerciser, because it checks two flag bits that real chips fill in differently from our definition. Two extra checks in our plan were not run either: comparing against another group's published per-instruction test vectors, and trying the worked examples from the Zilog manuals. Whether to add them is Sai's call.

## Next up

This closes the early-CPU part of our draft plan. The retro-machines track that follows needs a Z80 core, and this is it.

---
*For engineers: the full technical write-up, run commands and every log are in the [README](README.md).*
