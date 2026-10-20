/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#ifndef VNDN_L3_EXPERIMENT_TRACER_H
#define VNDN_L3_EXPERIMENT_TRACER_H

#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/data.hpp>
#include <ndn-cxx/lp/nack.hpp>
#include <cstdint>
#include <memory>
#include <string>

namespace vanet {

/** A logical NDN message, not an LP/MAC packet or proof of device acceptance. */
struct VndnL3Description
{
  std::string semanticClass;
  uint64_t wireBytes = 0;
  uint64_t innerDataBytes = 0;
};

/** Read-only subscriber to existing ndnSIM traces. No changes to the NFD stack. */
class VndnL3ExperimentTracer
{
public:
  static std::unique_ptr<VndnL3ExperimentTracer>
  InstallAll (const std::string &outputDirectory, int64_t startNs, int64_t endNs);
  ~VndnL3ExperimentTracer ();
  void Flush ();
  void Close ();

  static VndnL3Description Describe (const ndn::Interest &interest);
  static VndnL3Description Describe (const ndn::Data &data);
  static VndnL3Description Describe (const ndn::lp::Nack &nack);

private:
  struct Impl;
  explicit VndnL3ExperimentTracer (std::unique_ptr<Impl> impl);
  std::unique_ptr<Impl> m_impl;
};

} // namespace vanet
#endif
