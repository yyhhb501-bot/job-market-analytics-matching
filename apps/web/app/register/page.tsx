import { Suspense } from "react";

import MemberPhoneAuthForm from "@/components/MemberPhoneAuthForm";

export const dynamic = "force-dynamic";

export default function RegisterPage() {
  return (
    <Suspense>
      <MemberPhoneAuthForm intent="register" />
    </Suspense>
  );
}
