"use client";

import { useActionState, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Segmented } from "@/components/segmented";
import { setSimulatedWeekend, type DevClockState } from "@/lib/actions";
import type { WeekendSession } from "@/lib/types";

/*
  The simulator's clock, as a switch.

  Development only: the API's /weekend/session says whether the switch may
  exist (`dev_toggle`), and in production it says no, so this renders
  nothing there — the same way the API's /dev/clock does not exist there.

  Flipping it fakes exactly one thing, the clock. The whole app then behaves
  as it will on a real Saturday: the after-hours panel appears, the order
  ticket becomes the weekend ticket, quotes come from Jupiter, and the
  reserve maths runs against real sandbox journals. The stamp styling (the
  same amber as the paper-trading stamp) keeps it visually impossible to
  mistake for a production control.
*/

const INITIAL: DevClockState = { status: "idle" };

export function WeekendSwitch({
  initialSession,
}: {
  initialSession: WeekendSession;
}) {
  const [state, formAction, pending] = useActionState(setSimulatedWeekend, INITIAL);
  const queryClient = useQueryClient();
  const formRef = useRef<HTMLFormElement>(null);

  const session = state.status === "set" ? state.session : initialSession;

  // Everything on the page keys off the clock; when the simulated session
  // changes, every cached answer that mentions it is stale at once.
  useEffect(() => {
    if (state.status === "set") {
      void queryClient.invalidateQueries();
    }
  }, [state, queryClient]);

  if (!session.dev_toggle) return null;

  // On a real weekend the switch has nothing to fake.
  if (session.session === "weekend" && !session.simulated) {
    return (
      <p className="text-[12px] text-stamp">
        Dev · it&rsquo;s a real weekend — the engine is live on its own
      </p>
    );
  }

  const value = session.simulated ? "weekend" : "real";

  return (
    <form
      ref={formRef}
      action={formAction}
      className="flex items-center gap-3 rounded-control border border-stamp-rule bg-stamp-wash px-3 py-2"
    >
      <span className="text-[12px] font-medium tracking-[0.02em] text-stamp">
        Dev clock
      </span>
      {/* Always the opposite of what is showing: a change means "flip". */}
      <input
        type="hidden"
        name="simulate"
        value={value === "weekend" ? "false" : "true"}
      />
      <fieldset disabled={pending} className="border-0 p-0">
        <Segmented
          label="Simulated session"
          size="sm"
          options={[
            { value: "real", label: "Real time" },
            { value: "weekend", label: "Weekend" },
          ]}
          value={value}
          onChange={(next) => {
            if (next !== value) formRef.current?.requestSubmit();
          }}
        />
      </fieldset>
      {state.status === "error" ? (
        <span className="text-[12px] text-loss">{state.message}</span>
      ) : null}
    </form>
  );
}
