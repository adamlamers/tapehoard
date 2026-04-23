<script lang="ts">
	import type { HTMLAttributes } from "svelte/elements";
	import { cn } from "$lib/utils";

	let { class: className, children, ...rest }: HTMLAttributes<HTMLOListElement> = $props();
</script>

<ol
	class={cn(
		"flex flex-wrap items-center gap-1.5 break-words text-sm text-muted-foreground sm:gap-2.5",
		className
	)}
	{...rest}
>
	{@render children?.()}
</ol>
