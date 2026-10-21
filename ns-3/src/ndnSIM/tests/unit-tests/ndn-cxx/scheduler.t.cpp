/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include <ndn-cxx/util/scheduler.hpp>

#include "helper/ndn-stack-helper.hpp"
#include "ns3/simulator.h"
#include "boost-test.hpp"

#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace ns3 {
namespace ndn {
namespace tests {

class SchedulerFixture
{
public:
  SchedulerFixture()
  {
    StackHelper helper;
    helper.setCustomNdnCxxClocks();
    scheduler.reset(new ::ndn::Scheduler(io));
  }

  ~SchedulerFixture()
  {
    scheduler.reset();
    Simulator::Destroy();
  }

  ::ndn::DummyIoService io;
  std::unique_ptr<::ndn::Scheduler> scheduler;
};

BOOST_FIXTURE_TEST_SUITE(NdnCxxScheduler, SchedulerFixture)

BOOST_AUTO_TEST_CASE(DescendingDeadlinesHaveOneWakeupEach)
{
  std::vector<int> callbacks;
  const auto before = Simulator::GetEventCount();
  for (int i = 100; i > 0; --i) {
    scheduler->schedule(::ndn::time::milliseconds(i), [&, i] {
      BOOST_CHECK_EQUAL(Simulator::Now().GetMilliSeconds(), i);
      BOOST_CHECK_EQUAL(Simulator::GetContext(), Simulator::NO_CONTEXT);
      callbacks.push_back(i);
    });
  }
  Simulator::Run();
  BOOST_REQUIRE_EQUAL(callbacks.size(), 100);
  for (int i = 1; i <= 100; ++i) {
    BOOST_CHECK_EQUAL(callbacks.at(i - 1), i);
  }
  const auto wakeups = Simulator::GetEventCount() - before;
  BOOST_TEST_MESSAGE("business_callbacks=" << callbacks.size() << " kernel_wakeups=" << wakeups);
  BOOST_CHECK_EQUAL(wakeups, 100);
}

BOOST_AUTO_TEST_CASE(AscendingDeadlines)
{
  int callbacks = 0;
  const auto before = Simulator::GetEventCount();
  for (int i = 1; i <= 10; ++i) {
    scheduler->schedule(::ndn::time::milliseconds(i), [&, i] {
      BOOST_CHECK_EQUAL(++callbacks, i);
      BOOST_CHECK_EQUAL(Simulator::Now().GetMilliSeconds(), i);
    });
  }
  Simulator::Run();
  BOOST_CHECK_EQUAL(callbacks, 10);
  BOOST_CHECK_EQUAL(Simulator::GetEventCount() - before, 10);
}

BOOST_AUTO_TEST_CASE(EqualDeadlinesAndZeroDelay)
{
  std::vector<int> callbacks;
  const auto before = Simulator::GetEventCount();
  scheduler->schedule(::ndn::time::milliseconds(10), [&] { callbacks.push_back(1); });
  scheduler->schedule(::ndn::time::milliseconds(10), [&] { callbacks.push_back(2); });
  scheduler->schedule(::ndn::time::milliseconds(0), [&] { callbacks.push_back(0); });
  Simulator::Run();
  const std::vector<int> expected{0, 1, 2};
  BOOST_CHECK_EQUAL_COLLECTIONS(callbacks.begin(), callbacks.end(), expected.begin(), expected.end());
  BOOST_CHECK_EQUAL(Simulator::GetEventCount() - before, 2);
}

BOOST_AUTO_TEST_CASE(CancelHeadNonHeadAndRepeatedCancel)
{
  std::vector<int> callbacks;
  auto last = scheduler->schedule(::ndn::time::milliseconds(30), [&] { callbacks.push_back(3); });
  auto head = scheduler->schedule(::ndn::time::milliseconds(10), [&] { callbacks.push_back(1); });
  scheduler->schedule(::ndn::time::milliseconds(20), [&] { callbacks.push_back(2); });
  last.cancel();
  last.cancel();
  head.cancel();
  head.cancel();
  const auto before = Simulator::GetEventCount();
  Simulator::Run();
  BOOST_REQUIRE_EQUAL(callbacks.size(), 1);
  BOOST_CHECK_EQUAL(callbacks.front(), 2);
  BOOST_CHECK_EQUAL(Simulator::GetEventCount() - before, 1);
}

BOOST_AUTO_TEST_CASE(CallbackRescheduleAndCancel)
{
  std::vector<int> callbacks;
  auto canceled = scheduler->schedule(::ndn::time::milliseconds(30), [&] { callbacks.push_back(99); });
  scheduler->schedule(::ndn::time::milliseconds(10), [&] {
    callbacks.push_back(1);
    canceled.cancel();
    scheduler->schedule(::ndn::time::milliseconds(0), [&] { callbacks.push_back(2); });
    scheduler->schedule(::ndn::time::milliseconds(10), [&] { callbacks.push_back(3); });
  });
  const auto before = Simulator::GetEventCount();
  Simulator::Run();
  const std::vector<int> expected{1, 2, 3};
  BOOST_CHECK_EQUAL_COLLECTIONS(callbacks.begin(), callbacks.end(), expected.begin(), expected.end());
  BOOST_CHECK_EQUAL(Simulator::GetEventCount() - before, 2);
}

BOOST_AUTO_TEST_CASE(CancelAllLeavesNoWakeups)
{
  int callbacks = 0;
  scheduler->schedule(::ndn::time::milliseconds(20), [&] { ++callbacks; });
  scheduler->schedule(::ndn::time::milliseconds(10), [&] { ++callbacks; });
  scheduler->cancelAllEvents();
  const auto before = Simulator::GetEventCount();
  Simulator::Run();
  BOOST_CHECK_EQUAL(callbacks, 0);
  BOOST_CHECK_EQUAL(Simulator::GetEventCount() - before, 0);
}

BOOST_AUTO_TEST_CASE(CancelAllInsideCallback)
{
  int callbacks = 0;
  scheduler->schedule(::ndn::time::milliseconds(20), [&] { ++callbacks; });
  scheduler->schedule(::ndn::time::milliseconds(10), [&] {
    ++callbacks;
    scheduler->cancelAllEvents();
  });
  const auto before = Simulator::GetEventCount();
  Simulator::Run();
  BOOST_CHECK_EQUAL(callbacks, 1);
  BOOST_CHECK_EQUAL(Simulator::GetEventCount() - before, 1);
}

BOOST_AUTO_TEST_CASE(DestructionRemovesAllWakeups)
{
  scheduler->schedule(::ndn::time::milliseconds(20), [] { BOOST_ERROR("destroyed scheduler callback"); });
  scheduler->schedule(::ndn::time::milliseconds(10), [] { BOOST_ERROR("destroyed scheduler callback"); });
  scheduler.reset();
  // Do not invoke a stale raw-this callback on the buggy implementation.
  BOOST_CHECK(Simulator::IsFinished());
}

BOOST_AUTO_TEST_CASE(PreservesCallbackContext)
{
  std::vector<uint32_t> contexts;
  const auto before = Simulator::GetEventCount();
  for (uint32_t context : {7U, 8U}) {
    Simulator::ScheduleWithContext(context, Seconds(0), MakeEvent(std::function<void()>([&, context] {
      scheduler->schedule(::ndn::time::milliseconds(10), [&, context] {
        BOOST_CHECK_EQUAL(Simulator::Now().GetMilliSeconds(), 10);
        BOOST_CHECK_EQUAL(Simulator::GetContext(), context);
        contexts.push_back(Simulator::GetContext());
      });
    })));
  }
  Simulator::Run();
  const std::vector<uint32_t> expected{7, 8};
  BOOST_CHECK_EQUAL_COLLECTIONS(contexts.begin(), contexts.end(), expected.begin(), expected.end());
  BOOST_CHECK_EQUAL(Simulator::GetEventCount() - before, 4);
}

BOOST_AUTO_TEST_CASE(ExceptionStillSchedulesRemainingCallbacks)
{
  int callbacks = 0;
  scheduler->schedule(::ndn::time::milliseconds(10), [] { throw std::runtime_error("test callback"); });
  scheduler->schedule(::ndn::time::milliseconds(20), [&] { ++callbacks; });
  BOOST_CHECK_THROW(Simulator::Run(), std::runtime_error);
  Simulator::Run();
  BOOST_CHECK_EQUAL(callbacks, 1);
  BOOST_CHECK(Simulator::IsFinished());
}

BOOST_AUTO_TEST_CASE(EqualTimeCallbacksKeepQueueOrder)
{
  std::vector<int> callbacks;
  scheduler->schedule(::ndn::time::milliseconds(10), [&] { callbacks.push_back(1); });
  Simulator::Schedule(MilliSeconds(10), MakeEvent(std::function<void()>([&] { callbacks.push_back(3); })));
  scheduler->schedule(::ndn::time::milliseconds(10), [&] { callbacks.push_back(2); });
  Simulator::Run();
  const std::vector<int> expected{1, 2, 3};
  BOOST_CHECK_EQUAL_COLLECTIONS(callbacks.begin(), callbacks.end(), expected.begin(), expected.end());
}

BOOST_AUTO_TEST_CASE(RearmedWakeupUsesSimulatorTieOrder)
{
  std::vector<int> callbacks;
  scheduler->schedule(::ndn::time::milliseconds(10), [&] { callbacks.push_back(3); });
  Simulator::Schedule(MilliSeconds(10), MakeEvent(std::function<void()>([&] { callbacks.push_back(2); })));
  scheduler->schedule(::ndn::time::milliseconds(1), [&] { callbacks.push_back(1); });
  Simulator::Run();
  // Rearming the later deadline must obey the kernel's normal time/UID order.
  // We do not promise the ordering of a discarded, stale timer is preserved.
  const std::vector<int> expected{1, 2, 3};
  BOOST_CHECK_EQUAL_COLLECTIONS(callbacks.begin(), callbacks.end(), expected.begin(), expected.end());
}

BOOST_AUTO_TEST_SUITE_END()

} // namespace tests
} // namespace ndn
} // namespace ns3
