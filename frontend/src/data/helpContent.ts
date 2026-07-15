export type HelpBlock =
  | { type: 'paragraph'; text: string }
  | { type: 'list'; items: string[] }
  | { type: 'callout'; title: string; text: string; route: string; label: string };
export type HelpSection = { id: string; title: string; summary: string; blocks: HelpBlock[] };
export const HELP_VERSION = 'Guide v1.0';
export const helpSections: HelpSection[] = [
  { id: 'start-here', title: 'Start here', summary: 'The operating flow from procurement intelligence to a fundable deal.', blocks: [
    { type: 'paragraph', text: 'Oricred turns public procurement signals into a focused credit workflow. Start in Discover, move promising companies into Lead Inbox, then use Deal Pipeline to qualify, prepare credit, and execute.' },
    { type: 'list', items: ['Discover: find awards and tenders that signal a real commercial opportunity.', 'Lead Inbox: prioritize companies, find the right contact, and make the first touch.', 'Deal Pipeline: qualify the opportunity, make a credit decision, and track conditions through funding.'] },
    { type: 'paragraph', text: 'A useful credit lead has a credible supplier, meaningful award or contract signal, an understandable buyer, enough value to matter, and a practical path to reach the business.' },
    { type: 'callout', title: 'Next action', text: 'Start with the latest award signals and create a lead when the supplier and opportunity are worth pursuing.', route: '/discover?tab=awards', label: 'Open Discover' },
  ]},
  { id: 'discover', title: 'Discover', summary: 'Find relevant awards, validate the signal, and create the right lead.', blocks: [
    { type: 'paragraph', text: 'Awards are the primary lead source. Filter by supplier, buyer, value, award date, source, and whether a lead exists. Use Tenders for earlier signals, Past Due for time-sensitive follow-up, and Supplier History for context.' },
    { type: 'list', items: ['Value is an entry point for sizing, not a credit decision.', 'B-BBEE adds supplier and buyer context.', 'Contact readiness tells you whether outreach can begin or enrichment is needed.', 'Supplier resolution indicates whether the award was matched confidently.'] },
    { type: 'paragraph', text: 'Create Lead makes a new opportunity from an award. Open Lead takes you to an existing opportunity. Provisional suppliers or enrichment-needed states are useful signals, but verify the legal entity before credit work.' },
    { type: 'paragraph', text: 'Watch awards that need monitoring. Use Past Due for urgent work and Supplier History to see prior awards and contacts.' },
    { type: 'callout', title: 'Next action', text: 'Review awards with a clear supplier, relevant buyer, sufficient value, and a contact-ready signal.', route: '/discover?tab=awards', label: 'Review awards' },
  ]},
  { id: 'lead-inbox', title: 'Lead Inbox', summary: 'Prioritize outreach and turn a raw lead into a qualified conversation.', blocks: [
    { type: 'paragraph', text: 'Use priority score and its reasons to decide what deserves attention first, then use contact readiness to choose between outreach and enrichment.' },
    { type: 'list', items: ['Find contact opens enrichment when no usable person is attached.', 'Mark contacted after a real first touch.', 'Assign ownership so follow-up has a clear accountable person.', 'Open full detail for source evidence, notes, and audit history.'] },
    { type: 'paragraph', text: 'Use award, tender, and supplier-history links to verify what was won and who bought it. Reference the award, confirm delivery timing and cash-flow pressure, ask who owns finance or delivery, and record the outcome and next step in notes.' },
    { type: 'callout', title: 'Next action', text: 'Work the highest-priority contactable lead and capture the outcome before moving on.', route: '/leads', label: 'Open Lead Inbox' },
  ]},
  { id: 'deal-pipeline', title: 'Deal Pipeline', summary: 'Move qualified opportunities through sales, credit, and execution deliberately.', blocks: [
    { type: 'paragraph', text: 'The pipeline is divided into Sales, Credit, and Deal Execution. Cards show exact workflow, contact status, award value, and identity-enrichment warnings. Open a card to advance deliberately from its detail panel.' },
    { type: 'list', items: ['Sales: new lead, client contacted, qualified lead, and won opportunity.', 'Credit: preparation, review, pre-approval, and conditions precedent.', 'Deal Execution: term sheet exchange, contracts, and ready for RFF.', 'Funded and Lost / Declined are terminal trays that keep outcomes visible.'] },
    { type: 'paragraph', text: 'Before a credit decision, confirm supplier identity, award or tender evidence, buyer context, expected delivery, funding requirement, and risk signals. Conditions precedent should be explicit, owned, and tracked. Use decline reasons, audit history, and reopening deliberately.' },
    { type: 'callout', title: 'Next action', text: 'Choose one active opportunity whose next state is clear from its evidence and notes.', route: '/pipeline', label: 'Open Deal Pipeline' },
  ]},
  { id: 'signals', title: 'Signals and troubleshooting', summary: 'Interpret the signals and know when the workflow needs help.', blocks: [
    { type: 'paragraph', text: 'Suitability indicates fit with the funding profile. Buyer preference adds buyer and province context. Risk flags call for investigation. Contact sufficiency tells you whether outreach can begin. Lead score helps order work; it does not replace judgement.' },
    { type: 'list', items: ['Unresolved supplier: verify the legal entity and use enrichment.', 'No contact: request enrichment or use supplier history and source evidence.', 'Stale source data: ask an administrator to refresh the source.', 'Enrichment or CRM sync not progressing: ask an administrator to check the scheduled job.'] },
    { type: 'paragraph', text: 'When a signal conflicts with evidence, record the discrepancy in notes and avoid advancing until resolved. Administrators can refresh sources, enrichment, and CRM sync; users should keep commercial context and the next action current.' },
    { type: 'callout', title: 'Need a second look?', text: 'Return to the pipeline to inspect signals, notes, conditions, and audit history.', route: '/pipeline', label: 'Inspect pipeline' },
  ]},
];
export const helpSearchText = (section: HelpSection) => [section.title, section.summary, ...section.blocks.map(block => block.type === 'list' ? block.items.join(' ') : block.text)].join(' ').toLowerCase();
