/**
 * 搜索建议函数。
 * 每次输入变化都会调用一次 search，发起新的建议请求。
 * 只有最新一次发起的请求，其结果才允许调用 render；更早发起、
 * 但更晚返回的请求结果必须丢弃，不能调用 render。
 */
let latestToken = 0;

export async function search(query, fetchSuggestions, render) {
  const token = ++latestToken;
  const suggestions = await fetchSuggestions(query);
  render(suggestions);
}
