import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { navigateTo } from "../lib/navigation";

type Props = AnchorHTMLAttributes<HTMLAnchorElement> & { href: string };

/**
 * 内部路由链接：保留标准 <a> 语义与新标签页打开能力，普通点击走无刷新切换。
 */
export default function AppLink({ href, onClick, target, ...rest }: Props) {
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      target === "_blank" ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      !/^(\/|https?:\/\/|\?)/.test(href)
    ) {
      return;
    }
    const resolved = new URL(href, location.origin);
    if (resolved.origin !== location.origin || resolved.pathname !== location.pathname) return;
    event.preventDefault();
    navigateTo(resolved.search || "?");
  }
  return <a href={href} target={target} onClick={handleClick} {...rest} />;
}
