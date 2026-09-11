/**
 * Long-term memory for Amp.
 *
 * Loads the vault into context when a thread starts, marks knowledge
 * candidates, and synchronises the vault after every agent turn.
 *
 * The design differs from Claude Code, and here is why.
 *
 * 1. The summary is delivered by `agent.start`, not `session.start`.
 *    In Amp's types `session.start` has no return value: it is a
 *    fire-and-forget event. Only `agent.start` can put text into context via
 *    `{ message: { content } }`. So `session.start` prepares the summary and
 *    syncs the vault, and the first agent turn delivers it.
 *
 * 2. There is no `PreCompact` equivalent, and none is needed.
 *    Amp has no context-compaction event, and handlers receive the full
 *    thread history. Rescuing a conversation before compaction, as in Claude
 *    Code, is unnecessary.
 *
 * 3. There is no `SessionEnd` equivalent in Amp itself.
 *    The documentation states it plainly: `There is no session.end event`.
 *    This matches Karpathy's method, where a human saves the session.
 *
 * Scripts are invoked through `amp.$`, Bun's built-in shell. It behaves the
 * same on macOS, Linux and Windows, so there is no Windows-specific branch
 * here: the only difference is the Python interpreter name.
 */
import type { PluginAPI } from '@ampcode/plugin'

export const description =
  'Long-term memory: loads project state into context, marks knowledge candidates, synchronises the vault.'

/** Summary per thread, keyed by thread id. */
const pending = new Map<string, string>()
/** Threads already served: never deliver twice. */
const served = new Set<string>()

/** Script timeout, milliseconds. */
const TIMEOUT_MS = 25000

export default function (amp: PluginAPI) {
  const dir = new URL('.', import.meta.url).pathname
  const scripts = `${dir}scripts`

  /**
   * Find a working Python.
   *
   * On macOS and Linux it is `python3`. On Windows the python.org installer
   * provides `python`, while the Microsoft Store ships a `python3` stub that
   * opens the store instead of running. Hence this probing order, with the
   * result cached for the plugin's lifetime.
   */
  let python: string | null = null
  const findPython = async (): Promise<string | null> => {
    if (python) return python
    for (const candidate of ['python3', 'python']) {
      try {
        const probe = await amp.$`${candidate} -c "print(1)"`.quiet().nothrow()
        if (probe.exitCode === 0) {
          python = candidate
          return python
        }
      } catch {
        // Not on PATH, try the next candidate.
      }
    }
    return null
  }

  /**
   * Run a vault script, passing the working directory via stdin.
   *
   * The scripts expect the same JSON as Claude Code hooks, so one codebase
   * serves both agents without internal branching.
   */
  const run = async (script: string, cwd: string): Promise<string> => {
    const exe = await findPython()
    if (!exe) {
      amp.logger.log('vault: no Python found, skipping')
      return ''
    }
    const payload = JSON.stringify({ cwd, source: 'amp' })
    try {
      const result = await Promise.race([
        amp.$`echo ${payload} | ${exe} ${`${scripts}/${script}`}`.quiet().nothrow(),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), TIMEOUT_MS)),
      ])
      if (result === null) {
        amp.logger.log(`vault: ${script} did not answer within ${TIMEOUT_MS / 1000}s`)
        return ''
      }
      if (result.exitCode !== 0) {
        amp.logger.log(`vault: ${script} exited with code ${result.exitCode}`)
      }
      return result.stdout.toString().trim()
    } catch (err) {
      amp.logger.log(`vault: failed to run ${script}: ${err}`)
      return ''
    }
  }

  /** Project root. Amp gives a URI; the scripts need a plain path. */
  const projectDir = (): string => {
    const root = amp.system.workspaceRoot
    if (!root) return ''
    try {
      return amp.helpers.filePathFromURI(root)
    } catch {
      return ''
    }
  }

  // Thread start: sync the vault and prepare the summary.
  // It cannot be delivered here: the event accepts no return value.
  amp.on('session.start', async (event) => {
    const cwd = projectDir()
    if (!cwd) return
    const summary = await run('ltm_session_start.py', cwd)
    if (summary) {
      pending.set(event.thread.id, summary)
      amp.logger.log(`vault: summary ready, ${summary.length} characters`)
    }
  })

  // First agent turn: put the summary into context.
  // display: false - this is plumbing for the agent, not for the human.
  amp.on('agent.start', (event) => {
    const id = event.thread.id
    if (served.has(id)) return {}
    const summary = pending.get(id)
    if (!summary) return {}
    served.add(id)
    pending.delete(id)
    return { message: { content: summary, display: false } }
  })

  // Turn end: mark knowledge candidates and synchronise the vault.
  // The script checks for changes itself: on a clean tree it exits silently
  // without touching the network.
  amp.on('agent.end', async () => {
    const cwd = projectDir()
    if (!cwd) return
    await run('ltm_sync.py', cwd)
  })

  amp.registerCommand(
    'ltm-vault.status',
    {
      title: 'Long-term memory status',
      category: 'Long-term memory',
      description: 'Show where the vault was found and what awaits compilation.',
    },
    async (ctx) => {
      const cwd = projectDir()
      const out = await run('ltm_doctor.py', cwd)
      await ctx.ui.notify(out || 'The check returned nothing, see the plugin log.')
    },
  )

  amp.registerCommand(
    'ltm-vault.sync',
    {
      title: 'Synchronise memory now',
      category: 'Long-term memory',
      description: 'Mark knowledge candidates, commit and push changes.',
    },
    async (ctx) => {
      const cwd = projectDir()
      await run('ltm_sync.py', cwd)
      await ctx.ui.notify('Vault synchronised.')
    },
  )

  amp.onDispose(() => {
    pending.clear()
    served.clear()
  })
}
