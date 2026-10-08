import type { ReactNode } from 'react';
import { useLanguage } from '../../i18n/LanguageContext';
import {
  buildCitationDomId,
  localizeReportHeading,
  parseRestrictedMarkdown,
  type MarkdownBlock,
} from './reportPresentation';

interface SafeMarkdownProps {
  content?: string;
  blocks?: MarkdownBlock[];
  citationNamespace?: string;
  citationCount?: number;
}

function renderEvidenceReferences(
  text: string,
  citationNamespace: string | undefined,
  citationCount: number,
  evidenceLabel: (index: number) => string,
  keyPrefix: string,
): ReactNode[] {
  const parts = text.split(/(\[Evidence\s+\d+\])/gi);
  return parts.filter(Boolean).map((part, index) => {
    const match = /^\[Evidence\s+(\d+)\]$/i.exec(part);
    if (!match) return part;

    const evidenceNumber = Number.parseInt(match[1], 10);
    const canLink = Boolean(
      citationNamespace
      && evidenceNumber > 0
      && evidenceNumber <= citationCount,
    );
    const reference = (
      <span
        className="citation-card__index"
        data-evidence-reference={evidenceNumber}
      >
        [{evidenceNumber}]
      </span>
    );

    if (!canLink || !citationNamespace) {
      return <span key={`${keyPrefix}-evidence-${index}`}>{reference}</span>;
    }

    return (
      <a
        key={`${keyPrefix}-evidence-${index}`}
        href={`#${buildCitationDomId(citationNamespace, evidenceNumber)}`}
        aria-label={evidenceLabel(evidenceNumber)}
      >
        {reference}
      </a>
    );
  });
}

function renderInline(
  text: string,
  citationNamespace: string | undefined,
  citationCount: number,
  evidenceLabel: (index: number) => string,
): ReactNode[] {
  const tokens = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*)/g);

  return tokens.filter(Boolean).map((token, index) => {
    const key = `${index}-${token.slice(0, 12)}`;
    if (token.startsWith('**') && token.endsWith('**')) {
      return (
        <strong key={key}>
          {renderEvidenceReferences(
            token.slice(2, -2),
            citationNamespace,
            citationCount,
            evidenceLabel,
            key,
          )}
        </strong>
      );
    }
    if (token.startsWith('`') && token.endsWith('`')) {
      return <code key={key}>{token.slice(1, -1)}</code>;
    }
    if (token.startsWith('*') && token.endsWith('*')) {
      return (
        <em key={key}>
          {renderEvidenceReferences(
            token.slice(1, -1),
            citationNamespace,
            citationCount,
            evidenceLabel,
            key,
          )}
        </em>
      );
    }

    const lines = token.split('\n');
    return lines.map((line, lineIndex) => (
      <span key={`${key}-${lineIndex}`}>
        {lineIndex > 0 && <br />}
        {renderEvidenceReferences(
          line,
          citationNamespace,
          citationCount,
          evidenceLabel,
          `${key}-${lineIndex}`,
        )}
      </span>
    ));
  });
}

export function SafeMarkdown({
  content = '',
  blocks,
  citationNamespace,
  citationCount = 0,
}: SafeMarkdownProps) {
  const { language, t } = useLanguage();
  const resolvedBlocks = blocks ?? parseRestrictedMarkdown(content);
  const inline = (text: string) => renderInline(
    text,
    citationNamespace,
    citationCount,
    t.chat.evidenceReference,
  );

  return (
    <div className="safe-markdown">
      {resolvedBlocks.map((block, index) => {
        const key = `${block.type}-${index}`;
        switch (block.type) {
          case 'heading': {
            const Heading = `h${block.level}` as 'h1' | 'h2' | 'h3' | 'h4';
            return (
              <Heading key={key}>
                {inline(localizeReportHeading(block.text, language))}
              </Heading>
            );
          }
          case 'label':
            return (
              <h4 className="safe-markdown__label" key={key}>
                {inline(localizeReportHeading(block.text, language))}
              </h4>
            );
          case 'table':
            return (
              <div className="safe-markdown__table-wrap" key={key}>
                <table className="safe-markdown__table">
                  {block.headers && (
                    <thead>
                      <tr>
                        {block.headers.map((header, cellIndex) => (
                          <th scope="col" key={`${key}-header-${cellIndex}`}>
                            {inline(header)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                  )}
                  <tbody>
                    {block.rows.map((row, rowIndex) => (
                      <tr key={`${key}-row-${rowIndex}`}>
                        {row.map((cell, cellIndex) => (
                          <td key={`${key}-row-${rowIndex}-cell-${cellIndex}`}>
                            {inline(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case 'unordered-list':
            return (
              <ul key={key}>
                {block.items.map((item, itemIndex) => (
                  <li key={`${key}-${itemIndex}`}>{inline(item)}</li>
                ))}
              </ul>
            );
          case 'ordered-list':
            return (
              <ol key={key}>
                {block.items.map((item, itemIndex) => (
                  <li key={`${key}-${itemIndex}`}>{inline(item)}</li>
                ))}
              </ol>
            );
          case 'blockquote':
            return <blockquote key={key}>{inline(block.text)}</blockquote>;
          case 'horizontal-rule':
            return <hr key={key} />;
          case 'paragraph':
            return <p key={key}>{inline(block.text)}</p>;
        }
      })}
    </div>
  );
}
