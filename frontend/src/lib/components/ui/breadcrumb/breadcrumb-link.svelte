<script lang="ts">
	import type { HTMLAttributes } from "svelte/elements";
	import { cn } from "$lib/utils";

	let { class: className, children, ...rest }: HTMLAttributes<HTMLAnchorElement> = $props();
</script>

<a
	class={cn("transition-colors hover:text-foreground", className)}
	{...rest}
>
	{@render children?.()}
</a>
