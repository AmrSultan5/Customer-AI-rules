import { forwardRef, useImperativeHandle, useEffect, useMemo, useRef, useState } from 'react'
import { useEditor, EditorContent, Extension } from '@tiptap/react'
import { Plugin } from '@tiptap/pm/state'
import StarterKit from '@tiptap/starter-kit'

// ── Markdown serializer ────────────────────────────────────────────────────

function serializeInlines(nodes = []) {
  return nodes.map(n => {
    if (n.type === 'hardBreak') return '\n'
    let text = n.text ?? ''
    for (const mark of (n.marks ?? [])) {
      switch (mark.type) {
        case 'bold':   text = `**${text}**`; break
        case 'italic': text = `*${text}*`;   break
        case 'code':   text = `\`${text}\``; break
        case 'strike': text = `~~${text}~~`; break
      }
    }
    return text
  }).join('')
}

function serNode(node, listDepth = 0, listType = null, listIdx = 0) {
  const c = node.content ?? []
  switch (node.type) {
    case 'doc':
      return c.map(n => serNode(n)).filter(Boolean).join('\n\n')
    case 'paragraph':
      return serializeInlines(c)
    case 'bulletList':
      return c.map(n => serNode(n, listDepth, 'bullet')).join('\n')
    case 'orderedList':
      return c.map((n, i) => serNode(n, listDepth, 'ordered', i + 1)).join('\n')
    case 'listItem': {
      const ind = '  '.repeat(listDepth)
      const prefix = listType === 'ordered' ? `${ind}${listIdx}. ` : `${ind}- `
      const parts = c.map(n => {
        if (n.type === 'bulletList')  return '\n' + serNode(n, listDepth + 1, 'bullet')
        if (n.type === 'orderedList') return '\n' + serNode(n, listDepth + 1, 'ordered')
        return serializeInlines(n.content ?? [])
      })
      return prefix + parts.join('')
    }
    case 'codeBlock': {
      const lang = node.attrs?.language ?? ''
      const text = c.map(n => n.text ?? '').join('')
      return '```' + lang + '\n' + text + '\n```'
    }
    case 'blockquote':
      return c.map(n => '> ' + serNode(n)).join('\n')
    case 'heading':
      return '#'.repeat(node.attrs?.level ?? 1) + ' ' + serializeInlines(c)
    case 'horizontalRule':
      return '---'
    default:
      return c.map(n => serNode(n)).join('')
  }
}

function docToMarkdown(doc) {
  if (!doc) return ''
  return serNode(doc)
}

// ── Paste plugin: convert plain-text markdown bullets into list nodes ──────

function makePastePlugin() {
  return new Plugin({
    props: {
      handlePaste(view, event) {
        // If there's HTML on the clipboard, let Tiptap handle it (it parses <ul>/<li>)
        const html = event.clipboardData?.getData('text/html')
        if (html) return false

        const text = event.clipboardData?.getData('text/plain') ?? ''
        if (!text.trim()) return false

        const lines = text.split('\n')
        const contentLines = lines.filter(l => l.trim())
        const allBullets =
          contentLines.length > 0 &&
          contentLines.every(l => /^[-*+] /.test(l.trim()))

        if (allBullets) {
          const { schema, tr } = view.state
          const items = contentLines.map(l => l.replace(/^[-*+] /, '').trim())
          const listItems = items.map(t =>
            schema.nodes.listItem.create(null, [
              schema.nodes.paragraph.create(null, t ? [schema.text(t)] : []),
            ])
          )
          view.dispatch(tr.replaceSelectionWith(schema.nodes.bulletList.create(null, listItems)))
          return true
        }

        return false
      },
    },
  })
}

const PasteMarkdown = Extension.create({
  name: 'pasteMarkdown',
  addProseMirrorPlugins() {
    return [makePastePlugin()]
  },
})

// ── Component ──────────────────────────────────────────────────────────────

const RichInput = forwardRef(function RichInput(
  { onSend, placeholder, disabled, onIsEmptyChange },
  ref
) {
  const sendCbRef = useRef(onSend)
  sendCbRef.current = onSend

  const [isEmpty, setIsEmpty] = useState(true)

  const extensions = useMemo(
    () => [
      StarterKit,
      PasteMarkdown,
      Extension.create({
        name: 'keyHandler',
        addKeyboardShortcuts() {
          return {
            // Enter always sends
            Enter: () => {
              sendCbRef.current?.()
              return true
            },
            // Shift-Enter: continue a list item, or insert a hard break
            'Shift-Enter': ({ editor }) => {
              if (editor.isActive('listItem')) {
                return editor.commands.splitListItem('listItem')
              }
              return editor.commands.setHardBreak()
            },
          }
        },
      }),
    ],
    [] // eslint-disable-line react-hooks/exhaustive-deps
  )

  const editor = useEditor({
    extensions,
    editable: !disabled,
    onUpdate: ({ editor }) => {
      const empty = editor.isEmpty
      setIsEmpty(empty)
      onIsEmptyChange?.(empty)
    },
  })

  // Sync disabled → editable
  useEffect(() => {
    editor?.setEditable(!disabled)
  }, [editor, disabled])

  useImperativeHandle(ref, () => ({
    getMarkdown: () => docToMarkdown(editor?.getJSON()),
    clear:       () => editor?.commands.clearContent(true),
    focus:       () => editor?.commands.focus(),
    isEmpty:     () => editor?.isEmpty ?? true,
    setContent:  (text) => {
      const safe = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
      editor?.commands.setContent(
        `<p>${safe.replace(/\n/g, '</p><p>')}</p>`,
        false
      )
      editor?.commands.focus('end')
    },
  }), [editor])

  return (
    <div className="rich-input-wrap">
      {isEmpty && placeholder && (
        <div className="rich-placeholder" aria-hidden="true">{placeholder}</div>
      )}
      <EditorContent editor={editor} className="rich-input" />
    </div>
  )
})

export default RichInput
