import { PowerGuide } from "../guides/PowerGuide";
// import {FpgaConnectionGuide} from "../guides/FpgaConnectionGuide";


export default function SetupStep() {
  return (
    <section className="workspace-panel">
      {/* <FpgaConnectionGuide /> */}
      <PowerGuide />
    </section>
  );
}
