import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false, linkify: true })
// Release text is remote content. Allow web links, never HTML or remote images.
markdown.validateLink = url => /^https?:\/\//i.test(url)
markdown.disable('image')
markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return renderer.renderToken(tokens, index, options)
}
export function renderReleaseNotes(notes) {
  return markdown.render(typeof notes === 'string' ? notes : '')
}
