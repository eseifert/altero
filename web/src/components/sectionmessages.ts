/**
 * The line at the top of a section panel that says how the last thing went.
 *
 * Both panels — settings and administration — keep one; both have to forget it
 * at the same moment, which is why it is here rather than written twice. A
 * message is an account of one action, and the section that ran it is gone the
 * instant another is chosen: "Checked." from a retention rehearsal, still
 * standing over the overview, claims something was checked there.
 *
 * The route is what says the section changed, because that is where the
 * section lives — see `components/SectionPanel.vue`.
 */

import { ref, watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'

export interface SectionMessages {
  notice: Ref<string | null>
  failure: Ref<string | null>
  /** Forget both, so what is said next is only about what happens next. */
  clear(): void
}

export function useSectionMessages(): SectionMessages {
  const notice = ref<string | null>(null)
  const failure = ref<string | null>(null)
  const route = useRoute()

  function clear(): void {
    notice.value = null
    failure.value = null
  }

  watch(() => route.params.section, clear)

  return { notice, failure, clear }
}
