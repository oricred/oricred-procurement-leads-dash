import { HelpCircle } from 'lucide-react';
import { Link } from 'react-router-dom';

export default function HelpLink({ section, label = 'How do I get leads?' }: { section: string; label?: string }) {
  return <Link to={`/help#${section}`} className="inline-flex items-center gap-1.5 text-xs text-primary-400 hover:text-primary-300 transition-colors"><HelpCircle className="w-3.5 h-3.5" />{label}</Link>;
}
