import { useEffect, useMemo, useState } from 'react';
import { BookOpen, ChevronDown, Search } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { HELP_VERSION, helpSearchText, helpSections, type HelpBlock } from '../data/helpContent';

export default function HelpPage() {
  const location = useLocation();
  const [query, setQuery] = useState('');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const filtered = useMemo(() => { const needle = query.trim().toLowerCase(); return needle ? helpSections.filter(section => helpSearchText(section).includes(needle)) : helpSections; }, [query]);
  useEffect(() => { if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, [location.hash]);
  return <div className="max-w-6xl mx-auto">
    <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between mb-6"><div><div className="flex items-center gap-2 text-primary-400 mb-2"><BookOpen className="w-5 h-5" /><span className="text-xs uppercase tracking-widest">Operating guide · {HELP_VERSION}</span></div><h2 className="text-2xl font-semibold text-white">Turn procurement intelligence into credit leads</h2><p className="text-sm text-gray-400 mt-2 max-w-2xl">A practical guide to finding, prioritizing, qualifying, and advancing opportunities in Oricred.</p></div><div className="relative w-full md:w-64"><Search className="absolute left-3 top-2.5 w-4 h-4 text-gray-500" /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search this guide" className="w-full bg-surface-200 border border-surface-300 rounded-lg pl-9 pr-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-primary-500" /></div></div>
    <div className="lg:hidden mb-4"><button onClick={() => setMobileNavOpen(value => !value)} className="w-full flex items-center justify-between glass rounded-lg px-4 py-3 text-sm text-gray-200">Guide contents <ChevronDown className={`w-4 h-4 transition-transform ${mobileNavOpen ? 'rotate-180' : ''}`} /></button>{mobileNavOpen && <nav className="glass mt-1 rounded-lg p-2 space-y-1">{filtered.map(section => <a key={section.id} href={`#${section.id}`} onClick={() => setMobileNavOpen(false)} className="block px-3 py-2 text-sm text-gray-400 hover:text-primary-400">{section.title}</a>)}</nav>}</div>
    <div className="grid grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)] gap-8 items-start"><aside className="hidden lg:block sticky top-6"><p className="text-xs uppercase tracking-wider text-gray-600 mb-3">Contents</p><nav className="space-y-1 border-l border-surface-300">{filtered.map(section => <a key={section.id} href={`#${section.id}`} className="block border-l-2 border-transparent -ml-px px-3 py-2 text-sm text-gray-400 hover:text-primary-400 hover:border-primary-400">{section.title}</a>)}</nav></aside><div className="space-y-10">{filtered.length === 0 ? <div className="glass rounded-xl p-8 text-center text-gray-400">No guide sections match “{query}”.</div> : filtered.map(section => <section id={section.id} key={section.id} className="scroll-mt-6"><h3 className="text-xl font-semibold text-white">{section.title}</h3><p className="text-sm text-primary-300 mt-1 mb-4">{section.summary}</p><div className="space-y-4 text-sm leading-6 text-gray-300">{section.blocks.map((block, index) => <HelpBlockView key={index} block={block} />)}</div></section>)}</div></div>
  </div>;
}
function HelpBlockView({ block }: { block: HelpBlock }) {
  if (block.type === 'paragraph') return <p>{block.text}</p>;
  if (block.type === 'list') return <ul className="list-disc pl-5 space-y-2 marker:text-primary-400">{block.items.map(item => <li key={item}>{item}</li>)}</ul>;
  return <div className="rounded-lg border border-primary-500/20 bg-primary-500/5 p-4"><p className="font-medium text-primary-300">{block.title}</p><p className="text-gray-300 mt-1">{block.text}</p><Link to={block.route} className="inline-block mt-3 text-xs font-medium text-primary-400 hover:text-primary-300">{block.label} →</Link></div>;
}
